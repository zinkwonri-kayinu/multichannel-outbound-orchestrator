"""CLI: python -m outbound.cli --input valid.csv [--send]

Dry run by default: prints the routing plan and writes the exact payloads to
out/ without calling any API. Pass --send to push.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from .clients import HeyReach, Instantly
from .router import route, to_heyreach, to_instantly


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"missing env var {name} (see .env.example)")
    return value


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Push qualified leads to Instantly (email) and HeyReach (LinkedIn).")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--out", default=Path("out"), type=Path)
    p.add_argument("--send", action="store_true", help="actually call the APIs (default: dry run)")
    p.add_argument("--channels", default="email,linkedin", help="comma list: email, linkedin")
    args = p.parse_args(argv)
    channels = set(args.channels.split(","))

    with open(args.input, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    plan = route(rows)
    account_id = os.environ.get("HEYREACH_LINKEDIN_ACCOUNT_ID")
    email_payload = [to_instantly(r) for r in plan.email] if "email" in channels else []
    linkedin_payload = (
        [to_heyreach(r, int(account_id) if account_id else None) for r in plan.linkedin] if "linkedin" in channels else []
    )

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "instantly_leads.json").write_text(json.dumps(email_payload, indent=2), encoding="utf-8")
    (args.out / "heyreach_leads.json").write_text(json.dumps(linkedin_payload, indent=2), encoding="utf-8")
    (args.out / "skipped.json").write_text(json.dumps(plan.skipped, indent=2), encoding="utf-8")

    both = len({r["email"] for r in plan.email} & {r.get("email", "").strip().lower() for r in plan.linkedin})
    print(f"{len(rows)} leads -> email: {len(email_payload)}, linkedin: {len(linkedin_payload)} ({both} on both), skipped: {len(plan.skipped)}")

    if not args.send:
        print(f"dry run: payloads written to {args.out}/. Re-run with --send to push.")
        return 0

    report = {}
    if email_payload:
        report["instantly"] = Instantly(env("INSTANTLY_API_KEY")).add_leads(env("INSTANTLY_CAMPAIGN_ID"), email_payload)
    if linkedin_payload:
        report["heyreach"] = HeyReach(env("HEYREACH_API_KEY")).add_leads(int(env("HEYREACH_CAMPAIGN_ID")), linkedin_payload)
    (args.out / "push_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
