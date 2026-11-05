# Chris's CRE job finder

A Python 3.11+ job finder for commercial real estate and related financial/data analyst roles. No third-party Python packages are required.

## Your search

- Chicago, New York City (including boroughs), Richmond VA, and Minneapolis.
- On-site or hybrid roles; excludes locations labelled remote unless also labelled hybrid.
- Posted base salary **range minimum** must be at least $80,000. Unknown salaries appear in a separate section requiring verification. A $70k–$100k range is excluded.
- Real estate analysis, underwriting, valuation, acquisitions, asset/portfolio management and related finance/data roles.
- Matches Excel, Python, SQL, DCF, pro forma, lease abstraction, market research and other résumé skills.
- Excludes sales, brokerage, leasing-agent, fundraising and investor-relations titles; senior titles and roles explicitly requiring more than three years of experience are excluded by default.

Edit `config.toml` to adjust these preferences. Matching is deterministic and explainable; it does not require an LLM key. Job descriptions vary, so review the original posting. Salary and experience parsing are conservative heuristics, not verified employer facts. Only the location field establishes a city match; a city mentioned in the job description does not.

## Run locally

From the repository directory:

```bash
python -m unittest discover -s tests -v
python -m job_finder
```

The default is a **dry run**: no email is sent. Read `output/digest.txt` and `output/matches.json`. These generated files are ignored by Git. Failed sources are reported separately from zero matching jobs. If all sources fail, the command exits with status 2.

Live-verified feeds are configured for Fundrise (Lever), StepStone Group, Roofstock, Kiavi, Figure and Point72 (Greenhouse). These are starting points, not exhaustive coverage of the four cities. The live search checked 293 postings across six employers and generated seven potential matches with no source failures. Companies can retire or move their feeds; failures are reported explicitly. Add more `[[sources]]` entries with provider `greenhouse` or `lever`, company name and the ATS board identifier from the official careers link. Workday, LinkedIn and Indeed are not supported by this version; it does not bypass their access controls.

Required outbound HTTPS domains: `boards-api.greenhouse.io`, `api.lever.co`, and, for delivery, `api.resend.com`. Keep the platform proxy and TLS verification enabled.

## Connect email

1. Create a Resend account and verify a sender/domain you control. Resend's test sender generally cannot deliver to arbitrary recipients.
2. Store `RESEND_API_KEY` securely in environment settings. Set `EMAIL_FROM` to your verified sender address, such as `Jobs <jobs@your-verified-domain.example>` using your actual domain.
3. Confirm `search.recipient` in `config.toml`. It currently uses the email address supplied with your résumé.
4. Review a dry run, then run `python -m job_finder --send` to send a real digest.

Never commit credentials or paste them into chat. No email credential is included in this project. An accepted delivery request is recorded in `.data/history.sqlite3`; it does not guarantee inbox delivery. Failed sends are not marked as delivered. Resend idempotency keys reduce duplicates if the process fails after sending. No message is sent when there are no new matches. Preserve `.data` across runs to retain history.

## Daily automation

`.github/workflows/daily-jobs.yml` is prepared for GitHub Actions. It is **not active until committed/pushed to the default branch** and configured on GitHub:

1. Add repository Actions secret `RESEND_API_KEY` and Actions variable `EMAIL_FROM`. Cloud environment settings do not populate GitHub Actions secrets.
2. Run **Daily job digest → Run workflow** with `send_email` left unchecked to inspect the report artifact first.
3. Run manually with `send_email` checked to test actual delivery.
4. After a successful delivery test, set repository Actions variable `ENABLE_DAILY_EMAIL` to `true` to enable scheduled runs. Until then, scheduled jobs are skipped.
5. The scheduled run uses 14:00 UTC daily: 8 AM Chicago in winter, 9 AM during daylight saving time. GitHub may delay scheduled jobs.

The workflow caches SQLite history between runs. Cache eviction/deletion can cause previously emailed jobs to appear again; use durable external storage if stronger delivery guarantees are needed. The schedule runs on GitHub's default branch, and no persistent cloud background process is required. Source failures appear in workflow logs and reports; a partial search is identified in the digest.

## Validation status

Offline tests cover matching, exclusions, salary labels, provider parsing, history persistence, send failure behavior and the complete dry-run CLI. All six configured live feeds were validated successfully. Real email delivery remains untested pending email configuration. This is a working search implementation, not yet a running daily delivery service.
