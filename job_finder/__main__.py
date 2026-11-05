import argparse
import json
import os
import sys
import tomllib
from dataclasses import asdict
from pathlib import Path

from .core import History, Job, digest, evaluate, fetch, send_email


def main():
    parser = argparse.ArgumentParser(description="Find and rank CRE jobs. Default: dry run; no email sent.")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--state", default=".data/history.sqlite3")
    parser.add_argument("--output", default="output")
    parser.add_argument("--send", action="store_true", help="Email new matches via Resend")
    parser.add_argument("--fixture", help="Use local JSON jobs for offline validation; cannot send email")
    args = parser.parse_args()
    if args.fixture and args.send:
        parser.error("Fixture data cannot be emailed")
    with open(args.config, "rb") as handle:
        config = tomllib.load(handle)
    history = History(args.state)
    errors, jobs = [], []
    successful_sources = 0
    if args.fixture:
        jobs = [Job(**row) for row in json.loads(Path(args.fixture).read_text())]
        successful_sources = 1
    else:
        for source in config.get("sources", []):
            try:
                received = fetch(source)
                jobs.extend(received)
                successful_sources += 1
                print(f"{source['company']}: fetched {len(received)} jobs")
            except Exception as exc:
                # Do not print credentials or request headers.
                error = f"{source['company']}: {type(exc).__name__}"
                errors.append(error)
                print(error, file=sys.stderr)
    unique = {job.key: job for job in jobs}
    matches = []
    for job in unique.values():
        match = evaluate(job, config)
        if match and not history.contains(job.key):
            matches.append(match)
    matches.sort(key=lambda m: (-m.score, m.job.company, m.job.title))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = {"mode": "send" if args.send else "dry-run", "sources_succeeded": successful_sources,
              "source_errors": errors, "jobs_checked": len(unique), "matches": [asdict(m) for m in matches]}
    (output / "matches.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "digest.txt").write_text(digest(matches, errors))
    if not successful_sources:
        print("No sources succeeded. This is a failed search, not a zero-match result. See output/matches.json.", file=sys.stderr)
        return 2
    print(f"Checked {len(unique)} jobs; {len(matches)} new matches; {len(errors)} source failures.")
    if args.send and matches:
        try:
            result = send_email(matches, errors, config["search"]["recipient"],
                                os.environ.get("EMAIL_FROM"), os.environ.get("RESEND_API_KEY"))
            if not result.get("id"):
                raise ValueError("Email provider did not acknowledge delivery request")
        except Exception as exc:
            print(f"Email failed ({type(exc).__name__}); jobs remain unsent in history.", file=sys.stderr)
            return 3
        history.mark(matches)
        print("Email accepted by provider; matches recorded in history.")
    elif args.send:
        print("No new matches; no email sent.")
    else:
        print("Dry run: digest written; no email sent and no matches marked as delivered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
