"""
淘宝千牛卖家中心 — 浏览器适配器
基于 Playwright 接管千牛 Web 版
"""
import asyncio
from typing import Optional, Dict, Any, List, Callable, Awaitable
from pathlib import Path

from loguru import logger
from .base import BaseAdapter


class TaobaoAdapter(BaseAdapter):
    """
    淘宝千牛卖家客服适配器

    关键页面:
    - 登录: https://login.taobao.com/
    - 千牛卖家中心: https://myseller.taobao.com/home.htm
    - 聊天面板: 千牛 IM 内嵌 Web 组件

    消息监听策略:
    1. WebSocket 拦截 (主要)
    2. DOM MutationObserver (兜底)
    3. 定时轮询 IM 列表 (保底)
    """

    def __init__(self, **kwargs):
        super().__init__(platform="taobao", **kwargs)

        # 千牛特有的 DOM 选择器
        self.selectors = {
            # 登录检测
            "login_form": "#login-form, .login-box, [class*='login']",
            "logged_in_indicator": ".nick, .user-nick, .seller-info, [class*='seller-center']",

            # 消息列表
            "conversation_list": ".contact-list, .chat-list, [class*='recent-contact']",
            "conversation_item": ".contact-item, .chat-item, [class*='contact']",
            "unread_badge": ".badge, .unread-count, [class*='unread']",

            # 聊天面板
            "chat_panel": ".chat-panel, .message-panel, [class*='chat-content']",
            "message_list": ".message-list, .msg-list, [class*='msg-list']",
            "message_item": ".message-item, .msg-item, [class*='msg-item']",
            "incoming_message": ".msg-left, .msg-receive, [class*='left']",
            "user_name_element": ".contact-name, .user-name, [class*='nick']",

            # 输入区域
            "input_box": ".input-box textarea, .edit-area textarea, [contenteditable='true'], textarea",
            "send_button": ".send-btn, button[class*='send'], [class*='send-btn']",

            # 用户信息
            "user_info_panel": ".user-info, .profile-panel, [class*='user-card']",
        }

        # WS 拦截缓冲区
        self._ws_messages = []

    # ── 页面 URL ──────────────────────────────────

    async def login_url(self) -> str:
        return "https://login.taobao.com/member/login.jhtml"

    async def chat_url(self) -> str:
        return "https://myseller.taobao.com/home.htm/chat/message"

    async def check_logged_in(self) -> bool:
        """检查千牛登录状态"""
        try:
            # 方法1: 检查卖家后台特有元素
            logged_in = await self.page.evaluate("""
                () => {
                    // 检查是否有卖家昵称/会话列表等已登录特征
                    const nickElements = document.querySelectorAll('.nick, .seller-nick, [class*="seller-name"]');
                    const contactList = document.querySelectorAll('.contact-list, [class*="recent-contact"]');
                    const loginForm = document.querySelectorAll('#login-form, [class*="login-box"]');

                    // 有会话列表且没有登录表单 → 已登录
                    return (contactList.length > 0 || nickElements.length > 0) && loginForm.length === 0;
                }
            """)
            return bool(logged_in)

        except Exception:
            return False

    # ── 消息拦截 ──────────────────────────────────

    async def inject_interceptor(self):
        """注入千牛消息拦截脚本"""
        await self.page.evaluate("""
            (() => {
                // 1. WebSocket 拦截
                const origWebSocket = window.WebSocket;
                window.WebSocket = function(...args) {
                    const ws = new origWebSocket(...args);
                    ws.addEventListener('message', (event) => {
                        try {
                            const data = JSON.parse(event.data);
                            // 千牛/阿里旺旺的WS消息格式
                            if (data && (data.content || data.msg || data.body)) {
                                window.__kefu_ws_msg__(data);
                            }
                        } catch(e) {}
                    });
                    return ws;
                };
                window.WebSocket.prototype = origWebSocket.prototype;

                // 2. XHR/Fetch 拦截 (兜底轮询消息)
                const origFetch = window.fetch;
                window.fetch = async function(...args) {
                    const resp = await origFetch.apply(this, args);
                    try {
                        const clone = resp.clone();
                        const text = await clone.text();
                        // 检测千牛消息接口
                        if (args[0] && args[0].includes && (
                            args[0].includes('message') || args[0].includes('chat') ||
                            args[0].includes('im') || args[0].includes('ww')
                        )) {
                            window.__kefu_fetch_msg__(text);
                        }
                    } catch(e) {}
                    return resp;
                };

                // 3. DOM MutationObserver 兜底
                const msgContainer = document.querySelector('.message-list, .msg-list, [class*="msg-list"]');
                if (msgContainer) {
                    const observer = new MutationObserver((mutations) => {
                        for (const m of mutations) {
                            for (const node of m.addedNodes) {
                                if (node.nodeType === 1) {
                                    const msgText = node.innerText || node.textContent;
                                    if (msgText && msgText.trim().length > 0 && node.offsetParent !== null) {
                                        window.__kefu_dom_msg__({
                                            text: msgText.trim(),
                                            class: node.className,
                                            time: new Date().toISOString()
                                        });
                                    }
                                }
                            }
                        }
                    });
                    observer.observe(msgContainer, { childList: true, subtree: true });
                    console.log('[Kefu] DOM observer installed');
                }

                console.log('[Kefu] Interceptors injected for Taobao');
            })();
        """)

        # 暴露回调函数
        await self.page.expose_function("__kefu_ws_msg__", self._on_ws_message)
        await self.page.expose_function("__kefu_fetch_msg__", self._on_fetch_message)
        await self.page.expose_function("__kefu_dom_msg__", self._on_dom_message)

        logger.info("[Taobao] Interceptors injected")

    async def extract_message(self, raw_data: Any) -> Optional[Dict]:
        """从拦截数据提取标准消息格式"""
        try:
            # 千牛 WS 消息格式解析
            content = ""

            if isinstance(raw_data, dict):
                # 通用解析
                content = (
                    raw_data.get("content") or
                    raw_data.get("msg") or
                    raw_data.get("text") or
                    raw_data.get("message") or
                    raw_data.get("body", {}).get("content") or
                    ""
                )
                user_id = raw_data.get("from") or raw_data.get("senderId") or raw_data.get("uid") or ""
                user_name = raw_data.get("senderName") or raw_data.get("nick") or ""
                msg_id = raw_data.get("msgId") or raw_data.get("id") or ""
            else:
                content = str(raw_data)
                user_id = ""
                user_name = ""
                msg_id = ""

            if not content:
                return None

            # 过滤系统消息
            skip_patterns = ["系统消息", "欢迎光临", "机器人", "自动回复", "该用户已下线"]
            if any(p in content for p in skip_patterns):
                return None

            return {
                "platform": "taobao",
                "user_id": user_id,
                "user_name": user_name,
                "content": content,
                "msg_id": msg_id,
                "timestamp": None,  # 由总线补充
                "extra": {},
            }
        except Exception:
            return None

    # ── 消息发送 ──────────────────────────────────

    async def find_input_box(self):
        """定位千牛输入框"""
        selectors = [
            "textarea[placeholder*='输入']",
            "textarea[placeholder*='回复']",
            "div[contenteditable='true']",
            ".edit-area textarea",
            ".input-box textarea",
            "textarea",
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
        """定位千牛发送按钮"""
        selectors = [
            "button:has-text('发送')",
            "[class*='send-btn']",
            "button[class*='send']",
            ".toolbar button:last-child",
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
        """获取千牛会话列表"""
        try:
            contacts = await self.page.evaluate("""
                () => {
                    const items = document.querySelectorAll('.contact-item, [class*="contact-item"], .chat-item');
                    const results = [];
                    items.forEach(item => {
                        const name = item.querySelector('.nick, .name, [class*="name"]')?.innerText || '';
                        const lastMsg = item.querySelector('.last-msg, [class*="last-msg"]')?.innerText || '';
                        const unread = item.querySelector('.badge, .unread')?.innerText || '0';
                        if (name) {
                            results.push({ name: name.trim(), lastMsg: lastMsg.trim(), unread: parseInt(unread) || 0 });
                        }
                    });
                    return results;
                }
            """)
            return contacts
        except Exception:
            return []

    async def select_conversation(self, user_name: str):
        """选中千牛会话"""
        try:
            # 尝试通过用户名查找
            await self.page.evaluate(f"""
                () => {{
                    const items = document.querySelectorAll('.contact-item, [class*="contact-item"]');
                    for (const item of items) {{
                        const nameEl = item.querySelector('.nick, .name, [class*="name"]');
                        if (nameEl && nameEl.innerText.includes('{user_name}')) {{
                            item.click();
                            return true;
                        }}
                    }}
                    return false;
                }}
            """)
        except Exception:
            pass

    # ── 千牛 WS 回调 ──────────────────────────────

    async def _on_ws_message(self, raw_data):
        """WebSocket 消息回调"""
        msg = await self.extract_message(raw_data)
        if msg:
            await self._handle_new_message(msg)

    async def _on_fetch_message(self, raw_text: str):
        """Fetch 拦截回调"""
        try:
            import json
            data = json.loads(raw_text)
            msg = await self.extract_message(data)
            if msg:
                await self._handle_new_message(msg)
        except:
            pass

    async def _on_dom_message(self, data):
        """DOM Mutation 回调"""
        if isinstance(data, dict):
            msg = await self.extract_message(data)
        else:
            msg = await self.extract_message({"text": str(data)})
        if msg:
            await self._handle_new_message(msg)

    # ── 千牛特有功能 ──────────────────────────────

    async def get_buyer_info(self, user_id: str) -> Optional[Dict]:
        """获取买家信息 (购买记录等)"""
        try:
            # 千牛右侧通常有用户信息面板
            info = await self.page.evaluate("""
                () => {
                    const panel = document.querySelector('.user-info, .profile-panel, [class*="user-card"]');
                    if (!panel) return null;

                    return {
                        name: panel.querySelector('.name, [class*="name"]')?.innerText || '',
                        level: panel.querySelector('.level, [class*="level"]')?.innerText || '',
                        orderCount: panel.querySelector('[class*="order-count"]')?.innerText || '',
                        tags: Array.from(panel.querySelectorAll('.tag, [class*="tag"]')).map(t => t.innerText),
                    };
                }
            """)
            return info
        except Exception:
            return None

    async def send_image(self, to_user: str, image_path: Path) -> bool:
        """发送图片 (千牛支持粘贴截图)"""
        # 千牛支持 Ctrl+V 粘贴图片
        logger.info(f"[Taobao] Sending image: {image_path}")
        # 实际实现: 点击图片按钮 → 选择文件
        return False  # TODO: 实现图片发送

    async def mark_resolved(self, user_id: str):
        """标记会话已解决 (千牛的结束会话功能)"""
        try:
            close_btn = await self.page.query_selector('[class*="close-chat"], [class*="end-chat"]')
            if close_btn:
                await close_btn.click()
        except:
            pass
