"""
会话管理器 — 管理浏览器登录态和 Profile
"""
import asyncio
from typing import Dict, Optional
from pathlib import Path

from loguru import logger

from .taobao import TaobaoAdapter
from .douyin import DouyinAdapter
from .base import BaseAdapter


class SessionManager:
    """
    多平台会话管理

    职责:
    - 多店铺多平台适配器管理
    - Profile 目录管理
    - 登录态监控
    - 异常恢复
    """

    def __init__(self, profile_base: Path = None):
        self.profile_base = profile_base or Path("./browser_profiles")
        self.profile_base.mkdir(parents=True, exist_ok=True)

        # shop_id → platform → adapter
        self.adapters: Dict[str, Dict[str, BaseAdapter]] = {}

    async def create_adapter(self,
                             platform: str,
                             shop_id: str = "default",
                             message_callback=None) -> BaseAdapter:
        """创建适配器实例"""
        profile_dir = self.profile_base / platform / shop_id
        profile_dir.mkdir(parents=True, exist_ok=True)

        if platform == "taobao":
            adapter = TaobaoAdapter(
                profile_dir=profile_dir,
                headless=False,  # 生产环境 headless 可能被检测
                message_callback=message_callback,
            )
        elif platform == "douyin":
            adapter = DouyinAdapter(
                profile_dir=profile_dir,
                headless=False,
                message_callback=message_callback,
            )
        else:
            raise ValueError(f"Unknown platform: {platform}")

        return adapter

    async def start_adapter(self,
                            platform: str,
                            shop_id: str = "default",
                            message_callback=None) -> Optional[BaseAdapter]:
        """启动并注册适配器"""
        adapter = await self.create_adapter(platform, shop_id, message_callback)

        if not await adapter.launch():
            logger.error(f"Failed to launch {platform} adapter for {shop_id}")
            return None

        # 注册
        self.adapters.setdefault(shop_id, {})[platform] = adapter

        # 注入拦截器（启动后）
        if adapter.is_logged_in:
            asyncio.create_task(adapter.inject_interceptor())
            logger.info(f"[{platform}/{shop_id}] Interceptor injected")

        return adapter

    async def stop_all(self):
        """停止所有适配器"""
        for shop_id, platforms in self.adapters.items():
            for platform, adapter in platforms.items():
                logger.info(f"Stopping {platform}/{shop_id}...")
                await adapter.shutdown()
        self.adapters.clear()

    async def health_check(self) -> Dict:
        """全局健康检查"""
        status = {}
        for shop_id, platforms in self.adapters.items():
            for platform, adapter in platforms.items():
                key = f"{platform}/{shop_id}"
                status[key] = {
                    "running": adapter.is_running,
                    "logged_in": adapter.is_logged_in,
                    "messages_received": adapter.stats["messages_received"],
                    "messages_sent": adapter.stats["messages_sent"],
                    "errors": adapter.stats["errors"],
                    "restarts": adapter.stats["restarts"],
                }
        return status

    async def recover_dead(self):
        """恢复已死的适配器"""
        for shop_id, platforms in self.adapters.items():
            for platform, adapter in platforms.items():
                if not await adapter.is_alive():
                    logger.warning(f"[{platform}/{shop_id}] Dead, restarting...")
                    await adapter.restart()
                    if adapter.is_logged_in:
                        await adapter.inject_interceptor()

    def get_adapter(self, platform: str, shop_id: str = "default") -> Optional[BaseAdapter]:
        """获取适配器"""
        return self.adapters.get(shop_id, {}).get(platform)
