"""意图分类器单元测试"""
import pytest
from server.engine.intent import IntentClassifier


@pytest.fixture
def classifier():
    return IntentClassifier()


def test_greeting(classifier):
    result = classifier._keyword_match("你好")
    assert result is not None
    assert result["intent"] == "greeting"


def test_size_recommend(classifier):
    result = classifier._keyword_match("我160/50kg穿什么码？")
    assert result is not None
    assert result["intent"] == "presale"
    assert result["sub_intent"] == "size_recommend"


def test_refund_request(classifier):
    result = classifier._keyword_match("我要退货退款")
    assert result is not None
    assert result["intent"] == "aftersale"


def test_sentiment():
    classifier = IntentClassifier()
    assert classifier._detect_sentiment("谢谢你了") == "positive"
    assert classifier._detect_sentiment("你们是骗子") == "negative"

    # 普通消息
    assert classifier._detect_sentiment("这件有M码吗") == "neutral"


def test_escalation_needed():
    classifier = IntentClassifier()
    result = {"intent": "aftersale", "sub_intent": "refund", "sentiment": "negative"}
    escalate, reason = classifier.is_escalation_needed(result)
    assert escalate is True


def test_normal_no_escalation():
    classifier = IntentClassifier()
    result = {"intent": "presale", "sub_intent": "size_recommend", "sentiment": "neutral"}
    escalate, _ = classifier.is_escalation_needed(result)
    assert escalate is False
