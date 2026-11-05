"""Small HTTP helper with retries for transient errors."""

from __future__ import annotations

import time

import requests

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


def post_json(url: str, api_key: str, payload: dict, *, timeout: float = 60, retries: int = 3,
              session: requests.Session | None = None) -> tuple[dict, float]:
    """POST JSON, return (response_json, latency_ms). Retries with exponential backoff."""
    sess = session or requests
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "jev-ecommerce-reviews/0.1",
    }
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        start = time.perf_counter()
        try:
            resp = sess.post(url, json=payload, headers=headers, timeout=timeout)
            latency_ms = (time.perf_counter() - start) * 1000
            if resp.status_code in RETRY_STATUS and attempt < retries:
                last_err = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            else:
                if resp.status_code >= 400:
                    raise RuntimeError(f"HTTP {resp.status_code} from {url}: {resp.text[:500]}")
                return resp.json(), latency_ms
        except (requests.ConnectionError, requests.Timeout) as e:
            last_err = e
            if attempt >= retries:
                break
        time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"Request to {url} failed after {retries + 1} attempts: {last_err}")
