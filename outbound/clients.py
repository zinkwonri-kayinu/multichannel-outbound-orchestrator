"""Thin API clients. Batching and 429 backoff live here; nothing else talks HTTP."""

from __future__ import annotations

import time
from typing import Iterator

import requests


def batches(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class Client:
    base_url = ""
    batch_size = 100

    def __init__(self, api_key: str, session: requests.Session | None = None, max_retries: int = 4):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.max_retries = max_retries

    def headers(self) -> dict:
        raise NotImplementedError

    def post(self, path: str, body: dict) -> dict:
        for attempt in range(self.max_retries + 1):
            resp = self.session.post(self.base_url + path, json=body, headers=self.headers(), timeout=60)
            if resp.status_code == 429 and attempt < self.max_retries:
                time.sleep(float(resp.headers.get("Retry-After", 2**attempt)))
                continue
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        raise RuntimeError("unreachable")


class Instantly(Client):
    """Instantly API v2. Docs: https://developer.instantly.ai/api-reference/lead/add-leads-in-bulk-to-a-campaign-or-list"""

    base_url = "https://api.instantly.ai/api/v2"
    batch_size = 1000

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    def add_leads(self, campaign_id: str, leads: list[dict]) -> dict:
        totals = {"leads_uploaded": 0, "duplicated_leads": 0, "in_blocklist": 0, "invalid_email_count": 0}
        for chunk in batches(leads, self.batch_size):
            result = self.post(
                "/leads/add",
                {"campaign_id": campaign_id, "leads": chunk, "skip_if_in_workspace": True},
            )
            for key in totals:
                totals[key] += result.get(key, 0) or 0
        return totals


class HeyReach(Client):
    """HeyReach public API. Campaign must be ACTIVE with at least one LinkedIn sender assigned."""

    base_url = "https://api.heyreach.io/api/public"
    batch_size = 100

    def headers(self) -> dict:
        return {"X-API-KEY": self.api_key}

    def add_leads(self, campaign_id: int, pairs: list[dict]) -> dict:
        totals = {"addedLeadsCount": 0, "updatedLeadsCount": 0, "failedLeadsCount": 0}
        for chunk in batches(pairs, self.batch_size):
            result = self.post(
                "/campaign/AddLeadsToCampaignV2",
                {"campaignId": campaign_id, "accountLeadPairs": chunk},
            )
            for key in totals:
                totals[key] += result.get(key, 0) or 0
        return totals
