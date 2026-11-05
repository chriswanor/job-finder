import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from job_finder.core import History, Job, digest, evaluate, fetch, salary_status, send_email

ROOT = Path(__file__).resolve().parents[1]
CONFIG = tomllib.loads((ROOT / 'config.toml').read_text())


def job(**changes):
    data = dict(key='test:1', company='Example', title='Real Estate Financial Analyst',
                location='Chicago, IL', description='Real estate valuation, Excel, Python and DCF. Base salary $85,000 - $100,000.',
                url='https://example.com/jobs/1')
    return Job(**(data | changes))


class MatchingTests(unittest.TestCase):
    def test_matching_cities_and_salary(self):
        for city in ['Chicago, IL', 'New York, NY', 'Brooklyn, NY', 'Richmond, VA', 'Minneapolis, MN']:
            with self.subTest(city=city):
                match = evaluate(job(location=city), CONFIG)
                self.assertEqual(match.salary, 'confirmed')
                self.assertIn('Skill: Python', match.reasons)

    def test_exclusions(self):
        cases = [dict(title='Investment Sales Analyst'), dict(title='Real Estate Broker'),
                 dict(title='Senior Asset Management Analyst'), dict(title='Leasing Consultant'),
                 dict(location='Remote - New York'), dict(location='Richmond, CA'),
                 dict(location='Boston, MA'), dict(description='Real estate Excel. Salary $70,000 - $95,000.'),
                 dict(description='Real estate. 5+ years of experience required.'),
                 dict(description='Real estate. What is required: 7+ years of mortgage valuation experience.'),
                 dict(title='Investment Services Emerging Talent Network'),
                 dict(description='Real estate acquisitions with cold calling and commission-only pay.'),
                 dict(title='Software Engineer'), dict(title='Investor Relations Associate')]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertIsNone(evaluate(job(**changes), CONFIG))

    def test_unknown_salary_is_distinct(self):
        match = evaluate(job(description='Real estate valuation in Excel. Portfolio value $3,000,000.'), CONFIG)
        self.assertEqual(match.salary, 'unknown')
        self.assertIn('needs verification', digest([match], []))
        self.assertNotIn('starts at $80k', digest([match], []))

    def test_mentions_of_brokers_do_not_exclude_analyst(self):
        self.assertIsNotNone(evaluate(job(description='Analyze real estate data from brokers and sales teams.'), CONFIG))

    def test_hybrid_in_city_is_included(self):
        self.assertIsNotNone(evaluate(job(location='New York, NY (Hybrid)'), CONFIG))

    def test_related_role_needs_skill_overlap(self):
        self.assertIsNotNone(evaluate(job(title='Financial Analyst', description='Excel and Python financial modeling.'), CONFIG))
        self.assertIsNone(evaluate(job(title='Data Analyst', description='Marketing analytics.'), CONFIG))

    def test_salary_ranges(self):
        self.assertEqual(salary_status('Base salary $80k - $100k', 80000), 'confirmed')
        self.assertEqual(salary_status('Base salary $80,000.00 - $100,000.00.', 80000), 'confirmed')
        self.assertEqual(salary_status('Annual salary $75,000–$110,000', 80000), 'below')
        self.assertEqual(salary_status('Total compensation $120,000', 80000), 'unknown')

    def test_greenhouse_adapter(self):
        with patch('job_finder.core.request_json', return_value={'jobs': [dict(id=123, title='Analyst', location={'name': 'Chicago'}, content='<p>Real estate &amp; finance</p>', absolute_url='https://example.com/123')]}):
            result = fetch(dict(provider='greenhouse', board='example', company='Example'))
        self.assertEqual(result[0].description, 'Real estate & finance')
        self.assertEqual(result[0].key, 'greenhouse:example:123')

    def test_history_and_send_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            history = History(Path(directory) / 'history.sqlite3')
            match = evaluate(job(), CONFIG)
            self.assertFalse(history.contains(match.job.key))
            with patch('job_finder.core.request_json', side_effect=OSError('network down')):
                with self.assertRaises(OSError):
                    send_email([match], [], 'to@example.com', 'from@example.com', 'test-only')
            self.assertFalse(history.contains(match.job.key))
            history.mark([match])
            self.assertTrue(History(Path(directory) / 'history.sqlite3').contains(match.job.key))

    def test_end_to_end_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'jobs.json'
            fixture.write_text(json.dumps([job().__dict__, job(key='test:2', title='Investment Sales Analyst').__dict__]))
            command = [sys.executable, '-m', 'job_finder', '--fixture', str(fixture), '--output', directory, '--state', str(Path(directory) / 'history.sqlite3')]
            for _ in range(2):
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads((Path(directory) / 'matches.json').read_text())
                self.assertEqual(len(report['matches']), 1)
                self.assertEqual(report['jobs_checked'], 2)
            result = subprocess.run(command + ['--send'], cwd=ROOT, capture_output=True)
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
