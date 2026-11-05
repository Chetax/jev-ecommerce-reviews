import time

import pytest
from fastapi.testclient import TestClient

from jev_reviews.api import create_app
from jev_reviews.config import Settings
from jev_reviews.schema import Decision, Review
from jev_reviews.store import Store


class FakeClassifier:
    def __init__(self, name="fake"):
        self.name = name
        self.model_id = name

    def classify(self, r: Review) -> Decision:
        if "FAIL" in r.text:
            raise RuntimeError("boom")
        low = "Meh" in r.text
        return Decision(r.review_id, r.topic or "other", r.sentiment or "neutral", bool(r.defect),
                        bool(r.refund_request),
                        {"topic": 0.5 if low else 0.95, "sentiment": 0.9, "defect": 0.9, "refund_request": 0.9},
                        model=self.name, latency_ms=5, input_tokens=100, output_tokens=10, cost_usd=0.001)


def factory(spec):
    if spec == "jev":
        raise RuntimeError("TYPESAFE_API_KEY is not set.")
    if spec not in ("bedrock", "bedrock:x"):
        raise ValueError("Unknown model spec")
    return FakeClassifier(spec)


@pytest.fixture
def client():
    app = create_app(store=Store(":memory:"), settings=Settings(sheet_id="", typesafe_api_key=""),
                     classifier_factory=factory, workers=2)
    with TestClient(app) as c:
        yield c


def wait(c, url, key="status", done=("done", "failed")):
    for _ in range(200):
        body = c.get(url).json()
        if body[key] in done:
            return body
        time.sleep(0.02)
    raise AssertionError(f"timeout waiting on {url}")


def test_config(client):
    cfg = client.get("/api/config").json()
    assert cfg["jev_enabled"] is False and "product_quality" in cfg["topics"]
    assert any(m["spec"] == "jev" and m["disabled"] for m in cfg["models"])


def test_sample_run_lifecycle(client):
    r = client.post("/api/runs", json={"source": "sample", "model": "bedrock"})
    assert r.status_code == 201
    run = wait(client, f"/api/runs/{r.json()['id']}")
    assert run["status"] == "done" and run["done"] == run["total"] == 48
    rows = client.get(f"/api/runs/{run['id']}/decisions").json()
    assert len(rows) == 48 and rows[0]["review_id"] == "R001"
    flagged = [x for x in rows if x["needs_review"]]
    assert flagged and run["pending_review"] == len(flagged)

    # human correction
    target = flagged[0]
    p = client.patch(f"/api/runs/{run['id']}/decisions/{target['review_id']}",
                     json={"topic": "price_value" if target["topic"] != "price_value" else "other"})
    assert p.status_code == 200 and p.json()["reviewed"] and p.json()["corrected"]
    assert client.get(f"/api/runs/{run['id']}").json()["pending_review"] == len(flagged) - 1

    # approve without changes -> reviewed, not corrected
    other = rows[1]
    p = client.patch(f"/api/runs/{run['id']}/decisions/{other['review_id']}", json={})
    assert p.json()["reviewed"] and not p.json()["corrected"]

    csv = client.get(f"/api/runs/{run['id']}/export.csv")
    assert csv.status_code == 200 and csv.text.startswith("review_id,text,topic")
    assert client.delete(f"/api/runs/{run['id']}").status_code == 204
    assert client.get(f"/api/runs/{run['id']}").status_code == 404


def test_csv_upload_with_errors(client):
    text = "review_id,text\na,Great product\nb,FAIL please\n"
    r = client.post("/api/runs", json={"source": "csv", "csv_text": text, "model": "bedrock"})
    run = wait(client, f"/api/runs/{r.json()['id']}")
    assert run["done"] == 1 and run["failed"] == 1 and run["status"] == "done"
    rows = client.get(f"/api/runs/{run['id']}/decisions").json()
    assert rows[1]["error"].startswith("RuntimeError")
    assert client.patch(f"/api/runs/{run['id']}/decisions/b", json={}).status_code == 409


@pytest.mark.parametrize("body,code", [
    ({"source": "csv", "csv_text": "id,body\n1,x\n"}, 422),
    ({"source": "csv", "csv_text": "review_id,text\n1,x\n1,y\n"}, 422),
    ({"source": "csv"}, 422),
    ({"source": "sheet"}, 422),
    ({"source": "sample", "model": "jev"}, 422),
    ({"source": "sample", "model": "gpt"}, 422),
])
def test_run_validation(client, body, code):
    assert client.post("/api/runs", json={"model": "bedrock", **body}).status_code == code


def test_patch_validation(client):
    r = client.post("/api/runs", json={"source": "sample"}).json()
    wait(client, f"/api/runs/{r['id']}")
    assert client.patch(f"/api/runs/{r['id']}/decisions/R001", json={"topic": "nope"}).status_code == 422
    assert client.patch(f"/api/runs/{r['id']}/decisions/zzz", json={}).status_code == 404


def test_benchmark(client):
    r = client.post("/api/benchmarks", json={"models": ["bedrock", "bedrock:x"]})
    assert r.status_code == 201
    b = wait(client, f"/api/benchmarks/{r.json()['id']}")
    assert b["status"] == "done", b["error"]
    assert set(b["report"]["models"]) == {"bedrock", "bedrock:x"}
    assert b["progress"]["bedrock"]["done"] == 48
    assert client.post("/api/benchmarks", json={"models": ["jev"]}).status_code == 422
