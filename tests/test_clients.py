import pytest

from jev_reviews.config import Settings
from jev_reviews.jev_client import JevClassifier, parse_answers
from jev_reviews.schema import QUESTIONS, Review

JEV_ANSWERS = {
    "topic": {"type": "choice", "choice": "product_quality", "confidence": 0.93,
              "probabilities": {"product_quality": 0.93, "other": 0.07}},
    "sentiment": {"type": "score", "score": 0.05, "confidence": 0.88,
                  "legend": {"0": "Negative", "0.5": "Neutral", "1": "Positive"},
                  "probabilities": {"0": 0.88, "0.5": 0.1, "1": 0.02}},
    "defect": {"type": "noul", "noul": 0.97},
    "refund_request": {"type": "noul", "noul": 0.2},
}


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, str(data)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json, headers, timeout):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


SETTINGS = Settings(typesafe_api_key="k", typesafe_base_url="https://api.example/v1")
REVIEW = Review("R1", "Motor died after two uses.")


def test_parse_jev_answers():
    d = parse_answers("R1", JEV_ANSWERS, "typesafe/jev")
    assert (d.topic, d.sentiment, d.defect, d.refund_request) == ("product_quality", "negative", True, False)
    assert d.confidence == pytest.approx({"topic": 0.93, "sentiment": 0.88, "defect": 0.97, "refund_request": 0.8})


def test_score_with_label_probabilities():
    ans = dict(JEV_ANSWERS, sentiment={"score": 0.9, "probabilities": {"Negative": 0.1, "Neutral": 0.2, "Positive": 0.7}})
    d = parse_answers("R1", ans, "jev")
    assert d.sentiment == "positive" and d.confidence["sentiment"] == pytest.approx(0.7)


def test_score_without_legend_uses_range():
    ans = dict(JEV_ANSWERS, sentiment={"score": 0.52, "confidence": 0.6})
    assert parse_answers("R1", ans, "jev").sentiment == "neutral"


def test_unknown_topic_rejected():
    ans = dict(JEV_ANSWERS, topic={"choice": "nope", "confidence": 0.9})
    with pytest.raises(ValueError):
        parse_answers("R1", ans, "jev")


def test_jev_classifier_request_and_cost():
    sess = FakeSession(FakeResp({"answers": JEV_ANSWERS, "usage": {"input_tokens": 1000}}))
    d = JevClassifier(SETTINGS, session=sess).classify(REVIEW)
    call = sess.calls[0]
    assert call["url"] == "https://api.example/v1/systemone"
    assert call["headers"]["Authorization"] == "Bearer k"
    assert call["json"]["state"] == REVIEW.text and call["json"]["questions"] == QUESTIONS
    assert d.input_tokens == 1000 and d.cost_usd == pytest.approx(1000 / 1e6 * SETTINGS.jev_input_price_per_m)


def test_jev_retries_on_429(monkeypatch):
    monkeypatch.setattr("jev_reviews.http.time.sleep", lambda s: None)
    sess = FakeSession(FakeResp({}, 429), FakeResp({"answers": JEV_ANSWERS}))
    d = JevClassifier(SETTINGS, session=sess).classify(REVIEW)
    assert d.topic == "product_quality" and len(sess.calls) == 2


def test_jev_requires_key():
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        JevClassifier(Settings(typesafe_api_key="")).classify(REVIEW)
