"""
Agent Browser Skill 适配器

agent-browser 是一个本地安装的 Skill (CLI 工具), 不是 MCP Server。
通过子进程调用它来执行浏览器自动化任务。
"""
import asyncio
import json
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from pathlib import Path

from loguru import logger


@dataclass
class BrowserResult:
    success: bool
    data: Any = None
    screenshot_path: Optional[str] = None
    error: Optional[str] = None


class BrowserAdapter:
    """
    agent-browser Skill 适配器

    通过 CLI 子进程调用 agent-browser 技能:
    - agent-browser navigate <url>          → 打开页面
    - agent-browser screenshot <selector>    → 截图
    - agent-browser click <selector>        → 点击
    - agent-browser extract <selector>      → 提取数据
    - agent-browser fill <selector> <text>  → 填表
    """

    def __init__(self):
        self._screenshots_dir = Path("./data/screenshots")
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._available = shutil.which("agent-browser") is not None
        if self._available:
            logger.info("agent-browser skill detected")
        else:
            logger.info("agent-browser skill not found in PATH, browser actions disabled")

    @property
    def available(self) -> bool:
        return self._available

    # ── 高级操作方法 ──────────────────────────────

    async def navigate(self, url: str, wait_selector: str = "body") -> BrowserResult:
        """打开页面"""
        return await self._run("navigate", url, "--wait", wait_selector)

    async def screenshot(self, url: str = None, selector: str = "body") -> BrowserResult:
        """截图"""
        import time
        filename = f"screenshot_{int(time.time())}.png"
        filepath = self._screenshots_dir / filename

        args = ["screenshot", "--output", str(filepath)]
        if selector:
            args += ["--selector", selector]
        if url:
            args = ["navigate", url, "--wait", "body"] + args

        result = await self._run(*args)
        if result.success and filepath.exists():
            result.data = {"screenshot_path": str(filepath)}
            result.screenshot_path = str(filepath)
        return result

    async def extract(self, url: str, selector: str) -> BrowserResult:
        """抓取数据"""
        return await self._run("navigate", url, "--wait", selector,
                               "extract", "--selector", selector, "--format", "json")

    async def click(self, selector: str) -> BrowserResult:
        """点击元素"""
        return await self._run("click", selector)

    async def fill(self, selector: str, text: str) -> BrowserResult:
        """填表"""
        return await self._run("fill", selector, text)

    async def search_product(self, query: str, platform: str = "taobao") -> BrowserResult:
        """在平台上搜索商品"""
        urls = {
            "taobao": f"https://s.taobao.com/search?q={query}",
            "douyin": f"https://fxg.jinritemai.com/",
        }
        url = urls.get(platform, urls["taobao"])
        return await self.extract(url, ".item, .product, [class*='result']")

    async def check_policy(self, platform: str = "taobao") -> BrowserResult:
        """查看平台政策"""
        urls = {
            "taobao": "https://consumerservice.taobao.com/self-help",
        }
        url = urls.get(platform)
        if not url:
            return BrowserResult(success=False, error="Unknown platform")
        return await self.extract(url, "body")

    # ── 内部 ──────────────────────────────────────

    async def _run(self, *args: str) -> BrowserResult:
        if not self._available:
            return BrowserResult(
                success=False,
                error="agent-browser skill not installed. Run: npm install -g agent-browser"
            )

        cmd = ["agent-browser"] + list(args)
        logger.debug(f"Browser: {' '.join(cmd)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=30
            )

            if proc.returncode == 0:
                text = stdout.decode("utf-8", errors="replace").strip()
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    data = {"text": text}
                return BrowserResult(success=True, data=data)
            else:
                error = stderr.decode("utf-8", errors="replace").strip()
                return BrowserResult(success=False, error=error)

        except asyncio.TimeoutError:
            return BrowserResult(success=False, error="Browser action timed out (30s)")
        except FileNotFoundError:
            return BrowserResult(success=False, error="agent-browser not found")
        except Exception as e:
            return BrowserResult(success=False, error=str(e))


# 全局单例
browser_adapter = BrowserAdapter()
