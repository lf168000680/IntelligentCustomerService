"""
定时任务定义 — APScheduler 后台任务
"""
import asyncio
from datetime import datetime, timedelta, date
from typing import Dict

from loguru import logger


class JobScheduler:
    """
    24/7 定时任务调度

    任务周期:
    - 每 1 分钟: 健康检查
    - 每 5 分钟: 消息积压检查
    - 每 1 小时: 会话清理
    - 每天 02:00: 知识库学习
    - 每天 08:00: 发送日报
    """

    def __init__(self,
                 message_bus=None,
                 session_manager=None,
                 knowledge_pipeline=None,
                 db_factory=None):
        self.message_bus = message_bus
        self.session_manager = session_manager
        self.knowledge_pipeline = knowledge_pipeline
        self.db_factory = db_factory

        self._running = False
        self._tasks = []

    async def start(self):
        """启动所有定时任务"""
        self._running = True
        logger.info("JobScheduler started")

        # 启动异步循环任务
        self._tasks = [
            asyncio.create_task(self._health_check_loop()),
            asyncio.create_task(self._conversation_cleanup_loop()),
            asyncio.create_task(self._daily_learning_loop()),
        ]

    async def stop(self):
        """停止所有定时任务"""
        self._running = False
        for task in self._tasks:
            task.cancel()
        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except:
            pass
        logger.info("JobScheduler stopped")

    # ── 定时循环 ──────────────────────────────────

    async def _health_check_loop(self):
        """每分钟健康检查"""
        while self._running:
            try:
                await self._health_check()
            except Exception as e:
                logger.error(f"Health check error: {e}")
            await asyncio.sleep(60)

    async def _conversation_cleanup_loop(self):
        """每5分钟清理过期会话"""
        while self._running:
            try:
                await self._cleanup_stale()
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
            await asyncio.sleep(300)

    async def _daily_learning_loop(self):
        """每天凌晨2点知识学习"""
        while self._running:
            try:
                now = datetime.now()
                # 计算到凌晨2点的等待时间
                next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
                if now >= next_run:
                    next_run += timedelta(days=1)

                wait_seconds = (next_run - now).total_seconds()
                logger.info(f"Next learning run at {next_run} (in {wait_seconds:.0f}s)")
                await asyncio.sleep(wait_seconds)

                await self._run_learning()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Learning loop error: {e}")
                await asyncio.sleep(3600)  # 出错后等1小时

    # ── 任务实现 ──────────────────────────────────

    async def _health_check(self):
        """健康检查"""
        # 检查浏览器适配器
        if self.session_manager:
            status = await self.session_manager.health_check()
            for key, info in status.items():
                if not info["running"]:
                    logger.warning(f"Adapter {key} is not running!")
                if not info["logged_in"]:
                    logger.warning(f"Adapter {key} is not logged in!")

            # 自动恢复
            await self.session_manager.recover_dead()

        # 检查消息积压
        if self.message_bus:
            active = self.message_bus.get_active_count()
            if active > 20:
                logger.warning(f"High active sessions: {active}")

    async def _cleanup_stale(self):
        """清理过期会话"""
        if self.message_bus:
            self.message_bus.cleanup_stale_sessions(max_age_seconds=3600)

    async def _run_learning(self):
        """运行知识学习流水线"""
        if not self.knowledge_pipeline or not self.db_factory:
            logger.warning("Knowledge pipeline not available, skipping learning")
            return

        try:
            yesterday = date.today() - timedelta(days=1)
            logger.info(f"Starting daily knowledge learning for {yesterday}...")
            report = await self.knowledge_pipeline.run(
                date_range=(yesterday, yesterday)
            )
            logger.info(f"Learning complete: {report}")
        except Exception as e:
            logger.error(f"Knowledge learning failed: {e}")

    # ── 手动触发 ──────────────────────────────────

    async def trigger_learning(self, days_back: int = 1):
        """手动触发学习"""
        target_date = date.today() - timedelta(days=days_back)
        return await self.knowledge_pipeline.run(
            date_range=(target_date, target_date)
        )

    async def trigger_health_check(self) -> Dict:
        """手动触发健康检查"""
        await self._health_check()
        if self.session_manager:
            return await self.session_manager.health_check()
        return {"status": "ok"}
