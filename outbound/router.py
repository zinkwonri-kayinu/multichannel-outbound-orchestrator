"""Decide which channel(s) each lead goes to, and shape the payload for each API."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
LINKEDIN_RE = re.compile(r"^https?://(www\.)?linkedin\.com/in/[^/?#]+/?", re.I)

# Columns that become sequence variables on both channels.
CUSTOM_FIELDS = ("email_opener", "linkedin_message", "signal", "offer")


@dataclass
class Plan:
    email: list[dict] = field(default_factory=list)
    linkedin: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


def clean_email(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return value if EMAIL_RE.match(value) else None


def clean_linkedin(value: str | None) -> str | None:
    value = (value or "").strip()
    match = LINKEDIN_RE.match(value)
    if not match:
        return None
    # canonical form: https://www.linkedin.com/in/<slug>
    slug = match.group(0).rstrip("/").rsplit("/", 1)[1]
    return f"https://www.linkedin.com/in/{slug.lower()}"


def route(rows: list[dict]) -> Plan:
    """Email if there's a valid address, LinkedIn if there's a profile and a full name. Both if both."""
    plan = Plan()
    seen_emails, seen_profiles = set(), set()

    for row in rows:
        email = clean_email(row.get("email"))
        profile = clean_linkedin(row.get("linkedin_url"))
        has_name = bool(row.get("first_name", "").strip() and row.get("last_name", "").strip())
        routed, reasons = False, []

        if email and email not in seen_emails:
            seen_emails.add(email)
            plan.email.append({**row, "email": email})
            routed = True
        else:
            reasons.append("duplicate email" if email else "no valid email")

        if profile and has_name and profile not in seen_profiles:
            seen_profiles.add(profile)
            plan.linkedin.append({**row, "linkedin_url": profile})
            routed = True
        elif profile and not has_name:
            reasons.append("LinkedIn needs first + last name")
        else:
            reasons.append("duplicate LinkedIn profile" if profile else "no valid LinkedIn URL")

        if not routed:
            plan.skipped.append({**row, "skip_reason": "; ".join(reasons)})

    return plan


def custom_fields(row: dict) -> dict:
    return {k: row[k] for k in CUSTOM_FIELDS if row.get(k)}


def to_instantly(row: dict) -> dict:
    """Shape for POST /api/v2/leads/add (Instantly API v2)."""
    lead = {
        "email": row["email"],
        "first_name": row.get("first_name") or None,
        "last_name": row.get("last_name") or None,
        "company_name": row.get("company") or None,
        "job_title": row.get("title") or None,
        "website": row.get("domain") or None,
        "personalization": row.get("email_opener") or None,
    }
    if fields := custom_fields(row):
        lead["custom_variables"] = fields
    return {k: v for k, v in lead.items() if v is not None}


def to_heyreach(row: dict, linkedin_account_id: int | None = None) -> dict:
    """Shape for one accountLeadPairs entry (HeyReach AddLeadsToCampaignV2)."""
    lead = {
        "firstName": row["first_name"].strip(),
        "lastName": row["last_name"].strip(),
        "profileUrl": row["linkedin_url"],
        "companyName": row.get("company") or None,
        "position": row.get("title") or None,
        "emailAddress": clean_email(row.get("email")),
        "customUserFields": [{"name": k, "value": v} for k, v in custom_fields(row).items()] or None,
    }
    return {"linkedInAccountId": linkedin_account_id, "lead": {k: v for k, v in lead.items() if v is not None}}
