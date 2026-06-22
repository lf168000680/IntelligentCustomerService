"""
抖音飞鸽客服 — 浏览器适配器
基于 Playwright 接管飞鸽 Web 版
"""
import asyncio
from typing import Optional, Dict, Any, List
from pathlib import Path

from loguru import logger
from .base import BaseAdapter


class DouyinAdapter(BaseAdapter):
    """
    抖店飞鸽客服适配器

    关键页面:
    - 登录: https://fxg.jinritemai.com/ (飞鸽工作台)
    - 客服: https://fxg.jinritemai.com/pc/im

    消息监听策略:
    1. WebSocket 拦截 (飞鸽使用 WS 推送)
    2. DOM MutationObserver
    """

    def __init__(self, **kwargs):
        super().__init__(platform="douyin", **kwargs)

        self.selectors = {
            "login_form": "[class*='login'], .login-container",
            "logged_in_indicator": "[class*='shop-name'], .shop-info",
            "conversation_list": "[class*='conversation-list'], [class*='session-list']",
            "conversation_item": "[class*='conversation-item'], [class*='session-item']",
            "unread_badge": "[class*='unread'], .badge",
            "chat_panel": "[class*='chat-content'], [class*='message-container']",
            "message_list": "[class*='message-scroll'], [class*='msg-container']",
            "message_item": "[class*='message-item'], [class*='msg-row']",
            "incoming_message": "[class*='left'], [class*='receive']",
            "input_box": "textarea, [contenteditable='true'], [class*='input-area'] textarea",
            "send_button": "[class*='send-btn'], button:has-text('发送')",
            "order_panel": "[class*='order-panel'], [class*='order-info']",
        }

        # 飞鸽特有的 WS URL 模式
        self.ws_patterns = [
            "wss://frontier-im.douyin.com",
            "wss://im.jinritemai.com",
            "wss://fxg.jinritemai.com",
        ]

    async def login_url(self) -> str:
        return "https://fxg.jinritemai.com/"

    async def chat_url(self) -> str:
        return "https://fxg.jinritemai.com/pc/im"

    async def check_logged_in(self) -> bool:
        """检查飞鸽登录状态"""
        try:
            logged_in = await self.page.evaluate("""
                () => {
                    const shopInfo = document.querySelectorAll('[class*="shop-name"], [class*="shop-info"]');
                    const loginForm = document.querySelectorAll('.login-container, [class*="login-form"]');
                    const chatInput = document.querySelectorAll('textarea, [contenteditable="true"]');
                    return (shopInfo.length > 0 || chatInput.length > 0) && loginForm.length === 0;
                }
            """)
            return bool(logged_in)
        except:
            return False

    async def inject_interceptor(self):
        """注入飞鸽消息拦截脚本"""
        await self.page.evaluate("""
            (() => {
                // 1. WebSocket 拦截
                const origWebSocket = window.WebSocket;
                window.WebSocket = function(...args) {
                    const wsUrl = args[0] || '';
                    console.log('[Kefu] WS connecting:', wsUrl);

                    const ws = new origWebSocket(...args);

                    // 只拦截 IM 相关的 WS
                    if (wsUrl.includes('im') || wsUrl.includes('frontier') || wsUrl.includes('message')) {
                        ws.addEventListener('message', (event) => {
                            try {
                                const data = JSON.parse(event.data);
                                window.__kefu_dy_ws__(data);
                            } catch(e) {}
                        });
                    }

                    return ws;
                };
                window.WebSocket.prototype = origWebSocket.prototype;

                // 2. DOM Mutation Observer
                const findMsgContainer = () => {
                    return document.querySelector('[class*="message-scroll"], [class*="msg-container"], [class*="chat-content"]');
                };

                let retries = 0;
                const installObserver = () => {
                    const container = findMsgContainer();
                    if (container) {
                        const observer = new MutationObserver((mutations) => {
                            for (const m of mutations) {
                                for (const node of m.addedNodes) {
                                    if (node.nodeType === 1 && node.offsetParent !== null) {
                                        const text = node.innerText || node.textContent;
                                        if (text && text.trim()) {
                                            // 过滤自己发的消息
                                            const isOutgoing = node.classList && (
                                                node.classList.contains('right') ||
                                                node.className.includes('send') ||
                                                node.className.includes('outgoing')
                                            );
                                            if (!isOutgoing) {
                                                window.__kefu_dy_dom__({
                                                    text: text.trim(),
                                                    time: new Date().toISOString()
                                                });
                                            }
                                        }
                                    }
                                }
                            }
                        });
                        observer.observe(container, { childList: true, subtree: true });
                        console.log('[Kefu] DOM observer installed on Douyin');
                    } else if (retries < 10) {
                        retries++;
                        setTimeout(installObserver, 2000);
                    }
                };
                installObserver();

                console.log('[Kefu] Interceptors injected for Douyin');
            })();
        """)

        await self.page.expose_function("__kefu_dy_ws__", self._on_ws_message)
        await self.page.expose_function("__kefu_dy_dom__", self._on_dom_message)

        logger.info("[Douyin] Interceptors injected")

    async def extract_message(self, raw_data: Any) -> Optional[Dict]:
        """从飞鸽拦截数据提取标准消息"""
        try:
            content = ""
            user_id = ""
            user_name = ""

            if isinstance(raw_data, dict):
                # 飞鸽 WS 协议格式
                # 常见字段: content, text, msg_content, body.content
                body = raw_data.get("body", raw_data)
                if isinstance(body, dict):
                    content = body.get("content") or body.get("text") or body.get("msg") or ""
                    user_id = body.get("from_user_id") or body.get("user_id") or body.get("fromUid") or ""
                    user_name = body.get("nickname") or body.get("user_name") or ""

                # 另外一种格式
                if not content:
                    content = raw_data.get("msg_content") or raw_data.get("content") or ""
                    user_id = raw_data.get("from_user_id") or raw_data.get("user_id") or ""

            else:
                content = str(raw_data)

            if not content:
                return None

            # 过滤系统消息
            skip = ["系统提示", "欢迎来到", "已结束会话", "会话超时", "用户已离开"]
            if any(s in content for s in skip):
                return None

            return {
                "platform": "douyin",
                "user_id": user_id,
                "user_name": user_name,
                "content": content,
                "msg_id": str(hash(content))[:16],
                "timestamp": None,
                "extra": {},
            }
        except:
            return None

    async def find_input_box(self):
        """定位飞鸽输入框"""
        selectors = [
            "textarea",
            "div[contenteditable='true']",
            "[class*='input-area'] textarea",
        ]
        for sel in selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except:
                continue
        return None

    async def find_send_button(self):
        """定位飞鸽发送按钮"""
        selectors = [
            "button:has-text('发送')",
            "[class*='send-btn']",
            "[class*='send-button']",
        ]
        for sel in selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except:
                continue
        return None

    async def get_conversation_list(self) -> List[Dict]:
        """获取飞鸽会话列表"""
        try:
            return await self.page.evaluate("""
                () => {
                    const items = document.querySelectorAll('[class*="session-item"], [class*="conversation-item"]');
                    return Array.from(items).map(item => ({
                        name: item.querySelector('[class*="name"]')?.innerText || '',
                        lastMsg: item.querySelector('[class*="last-msg"], [class*="preview"]')?.innerText || '',
                        unread: parseInt(item.querySelector('[class*="unread"]')?.innerText || '0'),
                    }));
                }
            """)
        except:
            return []

    async def select_conversation(self, user_name: str):
        """选中飞鸽会话"""
        await self.page.evaluate(f"""
            () => {{
                const items = document.querySelectorAll('[class*="session-item"], [class*="conversation-item"]');
                for (const item of items) {{
                    const nameEl = item.querySelector('[class*="name"]');
                    if (nameEl && nameEl.innerText.includes('{user_name}')) {{
                        item.click();
                        return;
                    }}
                }}
            }}
        """)

    async def get_order_info(self, user_id: str) -> Optional[Dict]:
        """获取订单信息 (飞鸽右侧订单面板)"""
        try:
            return await self.page.evaluate("""
                () => {
                    const panel = document.querySelector('[class*="order-panel"], [class*="order-info"]');
                    if (!panel) return null;
                    return {
                        orderId: panel.querySelector('[class*="order-id"]')?.innerText || '',
                        status: panel.querySelector('[class*="status"]')?.innerText || '',
                        product: panel.querySelector('[class*="product-name"]')?.innerText || '',
                    };
                }
            """)
        except:
            return None

    async def _on_ws_message(self, raw_data):
        msg = await self.extract_message(raw_data)
        if msg:
            await self._handle_new_message(msg)

    async def _on_dom_message(self, data):
        if isinstance(data, dict):
            msg = await self.extract_message(data.get("text", ""))
        else:
            msg = await self.extract_message(str(data))
        if msg:
            await self._handle_new_message(msg)
