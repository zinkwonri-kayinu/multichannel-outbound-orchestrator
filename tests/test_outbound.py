import csv
import json
from pathlib import Path

from outbound.cli import main
from outbound.clients import HeyReach, Instantly
from outbound.router import clean_linkedin, route, to_heyreach, to_instantly

ROOT = Path(__file__).parent.parent
ROWS = list(csv.DictReader(open(ROOT / "examples" / "qualified_leads.csv", encoding="utf-8")))


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.content = json.dumps(body).encode()

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


def test_linkedin_urls_are_canonical():
    assert clean_linkedin("https://linkedin.com/in/Priya-Shah/") == "https://www.linkedin.com/in/priya-shah"
    assert clean_linkedin("https://www.linkedin.com/in/aishabello?utm_source=share") == "https://www.linkedin.com/in/aishabello"
    assert clean_linkedin("https://www.linkedin.com/company/acme") is None


def test_routing_by_available_channels():
    plan = route(ROWS)
    assert [r["first_name"] for r in plan.email] == ["Priya", "Marcus"]
    assert [r["first_name"] for r in plan.linkedin] == ["Priya", "Aisha", "Jon"]
    skipped = {r["first_name"] + r["signal"]: r["skip_reason"] for r in plan.skipped}
    assert "LinkedIn needs first + last name" in skipped["Sam"]
    assert "duplicate" in skipped["Priyaduplicate row"]


def test_instantly_payload_shape():
    lead = to_instantly(route(ROWS).email[1])
    assert lead["email"] == "marcus.lee@brightpath.com"
    assert lead["personalization"].startswith("Congrats")
    assert lead["custom_variables"] == {"email_opener": lead["personalization"], "signal": "new RevOps hire"}
    assert None not in lead.values()


def test_heyreach_payload_shape():
    pair = to_heyreach(route(ROWS).linkedin[1], linkedin_account_id=42)
    assert pair["linkedInAccountId"] == 42
    assert pair["lead"]["profileUrl"] == "https://www.linkedin.com/in/aishabello"
    assert {"name": "signal", "value": "raised $4M seed"} in pair["lead"]["customUserFields"]


def test_instantly_batches_and_sums(monkeypatch):
    session = FakeSession([FakeResponse(200, {"leads_uploaded": 1000}), FakeResponse(200, {"leads_uploaded": 5})])
    totals = Instantly("k", session=session).add_leads("camp", [{"email": f"{i}@x.com"} for i in range(1005)])
    assert totals["leads_uploaded"] == 1005
    assert [len(c["json"]["leads"]) for c in session.calls] == [1000, 5]
    assert session.calls[0]["headers"] == {"Authorization": "Bearer k"}


def test_heyreach_retries_on_429(monkeypatch):
    monkeypatch.setattr("outbound.clients.time.sleep", lambda s: None)
    session = FakeSession([FakeResponse(429, {}, {"Retry-After": "1"}), FakeResponse(200, {"addedLeadsCount": 2})])
    totals = HeyReach("k", session=session).add_leads(7, [{}, {}])
    assert totals["addedLeadsCount"] == 2
    assert len(session.calls) == 2
    assert session.calls[0]["url"].endswith("/campaign/AddLeadsToCampaignV2")


def test_dry_run_calls_nothing(tmp_path, capsys):
    main(["--input", str(ROOT / "examples" / "qualified_leads.csv"), "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert "email: 2, linkedin: 3 (1 on both), skipped: 2" in out
    assert "dry run" in out
    assert len(json.loads((tmp_path / "instantly_leads.json").read_text())) == 2
