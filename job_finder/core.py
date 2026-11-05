from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = TextParser()
    parser.feed(html.unescape(value or ""))
    return " ".join(" ".join(parser.parts).split())


@dataclass
class Job:
    key: str
    company: str
    title: str
    location: str
    description: str
    url: str


@dataclass
class Match:
    job: Job
    score: int
    salary: str
    reasons: list[str]


def request_json(url, payload=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": "CREJobFinder/0.1", "Accept": "application/json",
                 **({"Content-Type": "application/json"} if data else {}), **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch(source):
    board = source["board"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", board):
        raise ValueError("Invalid ATS board identifier")
    provider = source["provider"]
    if provider == "greenhouse":
        data = request_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
        rows = data["jobs"]
        return [Job(f"greenhouse:{board}:{j['id']}", source["company"], j["title"],
                    j.get("location", {}).get("name", ""), plain(j.get("content", "")),
                    j["absolute_url"]) for j in rows]
    if provider == "lever":
        rows = request_json(f"https://api.lever.co/v0/postings/{board}?mode=json")
        return [Job(f"lever:{board}:{j['id']}", source["company"], j["text"],
                    j.get("categories", {}).get("location", ""),
                    plain(j.get("descriptionPlain", "") + " " + " ".join(
                        x.get("content", "") for x in j.get("lists", []))), j["hostedUrl"])
                for j in rows]
    raise ValueError(f"Unsupported provider: {provider}")


CITY_PATTERNS = {
    "Chicago": r"\bchicago\b",
    "New York City": r"\b(?:new york(?: city)?|nyc|manhattan|brooklyn|queens|bronx|staten island)\b",
    "Richmond": r"\brichmond(?:,?\s+(?:va|virginia))\b",
    "Minneapolis": r"\bminneapolis\b",
}
# Restrict exclusions to role titles: an analyst description may discuss brokers or sales.
EXCLUDED = r"\b(?:sales|broker(?:age)?|realtor|leasing (?:agent|consultant)|account executive|business development|capital raising|fundrais\w*|investor relations)\b"
SENIOR = r"\b(?:senior|sr\.?|director|vice president|vp|head|chief|principal|managing|intern(?:ship)?)\b"
ROLE = r"\b(?:analyst|associate|underwrit\w*|asset manag\w*|portfolio manag\w*|investment|acquisitions|valuation|research|financial|data|development)\b"
DOMAIN = r"\b(?:real estate|property|properties|commercial lease|multifamily|mortgage|reit|proptech)\b"


def salary_status(description, minimum):
    # Parse compensation-labelled sentences only; avoid property values and bonuses.
    sentences = re.split(r"(?<!\d)\.(?!\d)|[;\n]", description)
    amounts = []
    for sentence in sentences:
        lower = sentence.lower()
        if not re.search(r"\b(?:base|salary|annual pay|annual compensation)\b", lower):
            continue
        if re.search(r"\b(?:hourly|per hour|/hour|/hr|ote|on.target|total compensation)\b", lower):
            continue
        values = re.findall(r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*([kK])?", sentence)
        parsed = [float(n.replace(",", "")) * (1000 if k else 1) for n, k in values]
        amounts.extend(n for n in parsed if n >= 10000)
    if not amounts:
        return "unknown"
    low = min(amounts)
    return "confirmed" if low >= minimum else "below"


def evaluate(job, config):
    search = config["search"]
    title = job.title.lower()
    location = job.location.lower()
    description = job.description.lower()
    if re.search(EXCLUDED, title) or re.search(SENIOR, title) or re.search(r"\b(?:talent network|talent pool|fellowship)\b", title):
        return None
    if re.search(r"\bremote\b", location) and not re.search(r"\bhybrid\b", location):
        return None
    if re.search(r"\b(?:commission.only|cold.calling|sales quota|outbound prospecting)\b", description):
        return None
    cities = [city for city in search["cities"] if re.search(CITY_PATTERNS[city], location)]
    if not cities or not re.search(ROLE, title):
        return None
    relevant_domain = bool(re.search(DOMAIN, title + " " + description))
    # Related finance/data roles must overlap specific resume skills.
    skills = [s for s in config["profile"]["skills"] if re.search(
        r"(?<!\w)" + re.escape(s.lower()) + r"(?!\w)", description)]
    if not relevant_domain and (not re.search(r"\b(?:financial|investment|data|portfolio)\b", title) or len(skills) < 2):
        return None
    for match in re.finditer(r"\b(\d+)\s*(?:[-–]\s*\d+)?\+?\s+years?\s+(?:of\s+)?(?:[a-z-]+\s+){0,5}experience", description):
        context = description[max(0, match.start()-30):match.end()+40]
        if re.search(r"building on|firm|company|founded|history", context):
            continue
        if "preferred" not in context and int(match.group(1)) > search["maximum_required_years"]:
            return None
    salary = salary_status(job.description, search["minimum_base_salary"])
    if salary == "below" or (salary == "unknown" and not search["include_unknown_salary"]):
        return None
    reasons = ["Location: " + ", ".join(cities)]
    if relevant_domain:
        reasons.append("Real estate relevance")
    reasons.extend("Skill: " + s for s in skills)
    return Match(job, 20 * relevant_domain + 5 * len(skills) + 10 * (salary == "confirmed"), salary, reasons)


class History:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS sent (job_key TEXT PRIMARY KEY, sent_at TEXT DEFAULT CURRENT_TIMESTAMP)")

    def contains(self, key):
        return self.db.execute("SELECT 1 FROM sent WHERE job_key = ?", (key,)).fetchone() is not None

    def mark(self, matches):
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO sent(job_key) VALUES (?)", [(m.job.key,) for m in matches])


def digest(matches, errors):
    lines = ["Chris, here are new job matches for your real estate and analytical skills.",
             "Matches are leads to review, not verified offers. Confirm requirements and base salary with the employer.", ""]
    for status, label in [("confirmed", "Posted base salary starts at $80k+"), ("unknown", "Salary undisclosed / needs verification")]:
        subset = [m for m in matches if m.salary == status]
        if not subset:
            continue
        lines += [label, "=" * len(label)]
        for m in subset:
            lines += [f"{m.job.title} — {m.job.company}", m.job.location,
                      "; ".join(m.reasons), m.job.url, ""]
    if errors:
        lines += ["Coverage warning: some sources could not be checked:", *errors, ""]
    return "\n".join(lines)


def send_email(matches, errors, recipient, sender, api_key):
    if not sender or not api_key:
        raise ValueError("Sending requires EMAIL_FROM (verified sender) and RESEND_API_KEY")
    fingerprint = hashlib.sha256((recipient + "\n" + "\n".join(sorted(m.job.key for m in matches))).encode()).hexdigest()
    return request_json("https://api.resend.com/emails", {
        "from": sender, "to": [recipient],
        "subject": f"{len(matches)} new real estate / analyst job matches",
        "text": digest(matches, errors),
    }, {"Authorization": f"Bearer {api_key}", "Idempotency-Key": fingerprint})
