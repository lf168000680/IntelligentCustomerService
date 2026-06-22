"""
意图分类器 — 识别客户消息的意图
"""
from typing import List, Dict, Optional, Tuple
from loguru import logger


class IntentClassifier:
    """
    客服意图分类

    分类维度:
    - 主意图: 售前咨询 / 订单查询 / 售后投诉 / 闲聊 / 其他
    - 子意图: 尺码推荐 / 面料询问 / 库存查询 / 物流催单 / 退款申请 ...
    - 情绪: positive / neutral / negative

    策略: 先用关键词快速匹配，置信度不够走 LLM
    """

    # 关键词 → (主意图, 子意图)
    KEYWORD_MAP: Dict[str, Tuple[str, str]] = {
        # ── 售前咨询 ──
        "尺码|码数|多大|大小|穿多大|什么码|偏大|偏小": ("presale", "size_recommend"),
        "面料|材质|成分|棉|麻|涤纶|天丝|羊毛|莫代尔": ("presale", "material"),
        "库存|有货|现货|预售|卖完|补货|断货": ("presale", "stock"),
        "搭配|配什么|怎么穿|怎么搭": ("presale", "styling"),
        "颜色|色差|有色差|好看吗|哪个颜色|选哪个": ("presale", "color"),
        "活动|优惠|折扣|包邮|满减|优惠券|便宜": ("presale", "promotion"),
        "清洗|洗护|洗涤|缩水|掉色|起球|变形": ("presale", "care"),
        "多久到|几天到|什么时候到|发货时间|到货": ("presale", "delivery_time"),
        "多少钱|价格|怎么卖|便宜点|优惠|能便宜": ("presale", "price"),
        "尺寸|胸围|腰围|肩宽|衣长|袖长|臀围": ("presale", "measurements"),
        "身高|体重|kg|cm|斤": ("presale", "size_recommend"),
        "穿上|上身|效果|好看|显瘦|显白|遮肉": ("presale", "appearance"),

        # ── 订单查询 ──
        "订单|发货|物流|快递|单号|到哪了|还没发|几天了": ("order", "tracking"),
        "改地址|换地址|修改地址|收货地址": ("order", "change_address"),
        "催货|催单|快点发|什么时候发|怎么还没发": ("order", "urge"),
        "还没收到|多久了|还没到": ("order", "delay"),

        # ── 售后投诉 ──
        "退货|退换|退款|仅退款|退钱|退一下": ("aftersale", "refund"),
        "换货|换一件|换码|换颜色|换个": ("aftersale", "exchange"),
        "质量|坏|破|漏|线头|掉色|掉毛|抽丝": ("aftersale", "quality_issue"),
        "差评|投诉|举报|店铺|投诉到": ("aftersale", "complaint"),
        "假货|假的|不是正品|仿冒": ("aftersale", "counterfeit"),
        "客服|转人工|人工客服|找老板": ("aftersale", "escalate"),
        "骂|脏话|无语|坑|骗子|差劲": ("aftersale", "angry"),

        # ── 闲聊/其他 ──
        "你好|在吗|在么|醒了没|上班": ("greeting", "greeting"),
        "谢谢|好的|OK|嗯|行|好吧|知道了": ("closing", "closing"),
        "拜拜|再见|晚安|早点休息": ("closing", "farewell"),
    }

    # 意图中文名
    INTENT_NAMES = {
        "presale": "售前咨询",
        "order": "订单查询",
        "aftersale": "售后处理",
        "greeting": "招呼问候",
        "closing": "结束对话",
        "other": "其他",
    }

    def __init__(self, llm_router=None):
        self.router = llm_router
        self.labels = list(self.INTENT_NAMES.keys())
        self.label_names = [f"{k}({v})" for k, v in self.INTENT_NAMES.items()]

    async def classify(self, text: str, use_llm: bool = True) -> Dict:
        """
        分类客户消息

        Returns:
            {
                "intent": "presale",
                "sub_intent": "size_recommend",
                "confidence": 0.95,
                "sentiment": "neutral",
                "method": "keyword" | "llm"
            }
        """
        result = {
            "intent": "other",
            "sub_intent": None,
            "confidence": 0.5,
            "sentiment": "neutral",
            "method": "keyword",
        }

        # Step 1: 关键词匹配
        keyword_result = self._keyword_match(text)
        if keyword_result and keyword_result["confidence"] >= 0.9:
            result.update(keyword_result)
            return result

        # Step 2: 情绪检测
        result["sentiment"] = self._detect_sentiment(text)

        # Step 3: LLM 分类 (如果置信度不够)
        if use_llm and self.router and keyword_result is None:
            try:
                llm_result = await self._llm_classify(text)
                if llm_result:
                    result.update(llm_result)
                    result["method"] = "llm"
            except Exception as e:
                logger.warning(f"LLM intent classification failed: {e}")
                if keyword_result:
                    result.update(keyword_result)

        return result

    def _keyword_match(self, text: str) -> Optional[Dict]:
        """关键词匹配"""
        import re

        best_score = 0
        best_match = None

        for pattern, (intent, sub_intent) in self.KEYWORD_MAP.items():
            matches = re.findall(pattern, text)
            if matches:
                # 匹配词越长，置信度越高
                max_len = max(len(m) for m in matches)
                score = min(0.99, 0.6 + max_len / 20.0)

                if score > best_score:
                    best_score = score
                    best_match = {
                        "intent": intent,
                        "sub_intent": sub_intent,
                        "confidence": round(score, 2),
                    }

        return best_match

    def _detect_sentiment(self, text: str) -> str:
        """简单情绪检测"""
        positive = ["谢谢", "好的", "OK", "嗯嗯", "不错", "喜欢", "满意", "好哒", "太好了", "开心"]
        negative = [
            "差", "投诉", "骗", "坑", "无语", "烂", "垃圾", "恶心", "失望",
            "退款", "退货", "差评", "举报", "投诉",
            "妈的", "操", "傻逼", "卧槽",
        ]

        pos_count = sum(1 for w in positive if w in text)
        neg_count = sum(1 for w in negative if w in text)

        # 强负面词权重更高
        strong_negative = ["妈的", "操", "傻逼", "卧槽", "垃圾", "恶心", "骗", "投诉"]
        strong_count = sum(1 for w in strong_negative if w in text)

        if strong_count > 0:
            return "negative"
        if neg_count > pos_count:
            return "negative"
        if pos_count > neg_count:
            return "positive"
        return "neutral"

    async def _llm_classify(self, text: str) -> Optional[Dict]:
        """LLM 意图分类"""
        if not self.router:
            return None

        prompt = f"""将用户消息分类。只输出 JSON，不要解释。

分类选项: {self.label_names}

用户消息: "{text}"

输出格式: {{"intent": "..."}}

JSON:"""

        result = await self.router.classify(
            text=text,
            labels=self.labels,
            system="你是一个客服意图分类器。将客户消息分类。",
        )

        # 清理输出
        result = result.strip().strip('`').strip()
        if result.startswith('{'):
            import json
            try:
                data = json.loads(result)
                return {
                    "intent": data.get("intent", "other"),
                    "sub_intent": data.get("sub_intent"),
                    "confidence": data.get("confidence", 0.7),
                }
            except json.JSONDecodeError:
                pass

        # 简易解析
        for label in self.labels:
            if label in result.lower():
                return {"intent": label, "sub_intent": None, "confidence": 0.7}

        return None

    def is_escalation_needed(self, intent_result: Dict, turn_count: int = 0) -> Tuple[bool, str]:
        """
        判断是否需要转人工

        Returns:
            (需要转人工?, 原因)
        """
        intent = intent_result.get("intent", "other")
        sub_intent = intent_result.get("sub_intent", "")
        sentiment = intent_result.get("sentiment", "neutral")

        # 售后投诉类 → 必须转
        if intent == "aftersale":
            if sub_intent in ("refund", "complaint", "counterfeit", "escalate"):
                return True, "客户要求退款/投诉/举报，需要人工处理"
            if sub_intent == "angry" and sentiment == "negative":
                return True, "客户情绪激动，需要人工安抚"

        # 连续多轮未解决
        if turn_count > 5 and intent != "closing":
            return True, f"已对话 {turn_count} 轮未解决，建议人工介入"

        # 客户明确要求
        if sub_intent == "escalate":
            return True, "客户明确要求转人工"

        return False, ""
