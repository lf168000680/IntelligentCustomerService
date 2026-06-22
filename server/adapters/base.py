"""
浏览器自动化适配器基类
所有平台的适配器继承此类
"""
import asyncio
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Callable, Awaitable
from pathlib import Path

from loguru import logger


class BaseAdapter(ABC):
    """
    平台适配器抽象基类

    职责:
    - 浏览器启动与管理
    - 消息监听 (DOM / WebSocket 拦截)
    - 消息发送 (模拟真人操作)
    - 会话保持 (Cookie / Profile 持久化)
    - 反检测

    子类:
    - TaobaoAdapter: 千牛卖家 Web 版
    - DouyinAdapter: 飞鸽客服 Web 版
    """

    def __init__(self,
                 platform: str,
                 profile_dir: Path = None,
                 headless: bool = False,
                 message_callback: Callable[[Dict], Awaitable[None]] = None):
        self.platform = platform
        self.headless = headless
        self.message_callback = message_callback  # async (msg_dict) -> None

        # 浏览器实例
        self.browser = None
        self.context = None
        self.page = None

        # Profile 目录 (持久化登录态)
        self.profile_dir = profile_dir or Path("./browser_profiles") / platform

        # 状态
        self.is_running = False
        self.is_logged_in = False
        self.last_heartbeat = 0
        self.heartbeat_interval = 30  # 秒
        self._heartbeat_task = None

        # 消息队列
        self.pending_messages: asyncio.Queue = asyncio.Queue()

        # 统计
        self.stats = {
            "messages_received": 0,
            "messages_sent": 0,
            "errors": 0,
            "restarts": 0,
        }

    @abstractmethod
    async def login_url(self) -> str:
        """登录页面 URL"""
        ...

    @abstractmethod
    async def chat_url(self) -> str:
        """客服聊天页面 URL"""
        ...

    @abstractmethod
    async def check_logged_in(self) -> bool:
        """检查是否已登录"""
        ...

    @abstractmethod
    async def inject_interceptor(self):
        """注入消息拦截脚本"""
        ...

    @abstractmethod
    async def extract_message(self, raw_data: Any) -> Optional[Dict]:
        """
        从原始拦截数据中提取消息

        Returns:
            {
                "platform": "...",
                "user_id": "...",
                "user_name": "...",
                "content": "...",
                "msg_id": "...",
                "timestamp": "...",
                "extra": {...}
            }
        """
        ...

    @abstractmethod
    async def find_input_box(self):
        """定位消息输入框"""
        ...

    @abstractmethod
    async def find_send_button(self):
        """定位发送按钮"""
        ...

    @abstractmethod
    async def get_conversation_list(self) -> List[Dict]:
        """获取会话列表"""
        ...

    @abstractmethod
    async def select_conversation(self, user_id: str):
        """选中某个会话"""
        ...

    # ── 通用方法 ──────────────────────────────────

    async def launch(self) -> bool:
        """启动浏览器"""
        try:
            from playwright.async_api import async_playwright

            self.playwright = await async_playwright().start()

            # 确保 profile 目录存在
            self.profile_dir.mkdir(parents=True, exist_ok=True)

            # 持久化上下文 (保持登录态)
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                # 反检测参数
                ignore_https_errors=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )

            # 注入反检测脚本
            await self._inject_stealth()

            # 打开页面
            self.page = await self.context.new_page()

            # 尝试检测登录状态
            self.is_logged_in = await self._ensure_logged_in()

            if self.is_logged_in:
                logger.info(f"[{self.platform}] Logged in successfully")
            else:
                logger.warning(f"[{self.platform}] Not logged in, need manual login")

            self.is_running = True

            # 启动心跳
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            return True

        except Exception as e:
            logger.error(f"[{self.platform}] Launch failed: {e}")
            self.stats["errors"] += 1
            return False

    async def shutdown(self):
        """关闭浏览器"""
        self.is_running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()

        logger.info(f"[{self.platform}] Shut down")

    async def restart(self) -> bool:
        """重启适配器"""
        logger.warning(f"[{self.platform}] Restarting...")
        await self.shutdown()
        await asyncio.sleep(2)
        self.stats["restarts"] += 1
        return await self.launch()

    async def send_message(self, to_user: str, content: str, typing_delay: bool = True) -> bool:
        """
        发送消息，模拟真人操作

        Args:
            to_user: 目标用户 ID
            content: 消息内容
            typing_delay: 是否模拟打字延迟
        """
        try:
            # 选中会话
            await self.select_conversation(to_user)

            # 模拟打字延迟
            if typing_delay:
                delay = min(0.05, len(content) / 200)  # 每条消息0.05-2秒延迟
                await asyncio.sleep(delay)

            # 定位输入框
            input_box = await self.find_input_box()
            if not input_box:
                logger.error(f"[{self.platform}] Input box not found")
                return False

            # 逐字输入 (模拟真人)
            await input_box.click()
            await input_box.fill("")  # 清空

            if typing_delay:
                # 逐字输入，随机间隔
                for char in content:
                    await self.page.keyboard.type(char, delay=50 + asyncio.get_event_loop().time() % 100)
                await asyncio.sleep(0.3)
            else:
                await input_box.fill(content)

            # 点击发送
            send_btn = await self.find_send_button()

            # 也支持 Enter 发送
            if send_btn:
                await send_btn.click()
            else:
                await self.page.keyboard.press("Enter")

            self.stats["messages_sent"] += 1

            # 随机"阅读"延迟 (模拟看手机)
            await asyncio.sleep(1 + (asyncio.get_event_loop().time() % 10) / 10)

            return True

        except Exception as e:
            logger.error(f"[{self.platform}] Send message failed: {e}")
            self.stats["errors"] += 1
            return False

    async def send_typing_indicator(self):
        """模拟正在输入状态 (部分平台支持)"""
        try:
            input_box = await self.find_input_box()
            if input_box:
                await input_box.click()
                await self.page.keyboard.type("...", delay=100)
                await asyncio.sleep(0.5)
                await input_box.fill("")
        except:
            pass

    async def is_alive(self) -> bool:
        """健康检查"""
        if not self.is_running:
            return False

        try:
            # 检查页面是否还在
            if self.page:
                await self.page.title()
                return True
        except Exception:
            return False

        return False

    # ── 内部方法 ──────────────────────────────────

    async def _inject_stealth(self):
        """注入反检测脚本"""
        if not self.context:
            return

        # 为所有新页面注入
        await self.context.add_init_script("""
            // 隐藏 webdriver 特征
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });

            // 覆盖 chrome 对象
            window.chrome = { runtime: {} };

            // 覆盖权限查询
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );
        """)

    async def _ensure_logged_in(self) -> bool:
        """确保登录态"""
        try:
            # 先尝试访问聊天页面
            chat_page = await self.chat_url()
            await self.page.goto(chat_page, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(3)

            # 检查是否已登录
            return await self.check_logged_in()

        except Exception as e:
            logger.warning(f"[{self.platform}] Login check failed: {e}")
            return False

    async def _heartbeat_loop(self):
        """心跳循环"""
        while self.is_running:
            await asyncio.sleep(self.heartbeat_interval)

            try:
                if self.page and self.is_running:
                    # 轻度交互保活
                    await self.page.evaluate("window.scrollBy(0, 1)")
                    self.last_heartbeat = asyncio.get_event_loop().time()

                    # 检查登录态
                    logged_in = await self.check_logged_in()
                    if not logged_in and self.is_logged_in:
                        logger.warning(f"[{self.platform}] Session expired!")
                        self.is_logged_in = False
                        # 触发重新登录通知

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.platform}] Heartbeat error: {e}")

    async def _handle_new_message(self, msg: Dict):
        """处理新消息"""
        self.stats["messages_received"] += 1

        if self.message_callback:
            try:
                await self.message_callback(msg)
            except Exception as e:
                logger.error(f"[{self.platform}] Message callback error: {e}")

        await self.pending_messages.put(msg)
