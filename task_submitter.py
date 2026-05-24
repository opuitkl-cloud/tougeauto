"""Playwright 浏览器自动化 - 题目读取、代码提交、结果获取"""

import os
import time
import random
import asyncio
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from config import HEADLESS, BROWSER_TIMEOUT, EVALUATE_TIMEOUT

MAIN_SITE = "https://www.educoder.net"
STORAGE_FILE = os.path.join(os.path.dirname(__file__), "browser_state.json")


class BrowserSession:
    """管理 Playwright 浏览器会话，供所有模块共享。
    使用持久化存储登录态（EduCoder、DeepSeek 等网站一次登录后自动复用）。
    """

    def __init__(self):
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None

    async def start(self):
        """启动浏览器，加载持久化的登录状态"""
        self.playwright = await async_playwright().start()

        storage_state = None
        if os.path.exists(STORAGE_FILE):
            storage_state = STORAGE_FILE

        self.browser = await self.playwright.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            storage_state=storage_state,
            permissions=["clipboard-read", "clipboard-write"],
        )
        self.page = await self.context.new_page()
        self.page.set_default_timeout(BROWSER_TIMEOUT)

    async def save_state(self):
        """保存浏览器状态（用于下次复用 DeepSeek 等网站的登录态）"""
        state = await self.context.storage_state()
        import json
        with open(STORAGE_FILE, "w") as f:
            json.dump(state, f)

    async def close(self):
        """关闭浏览器并保存状态"""
        try:
            if self.context:
                await self.save_state()
        except Exception:
            pass
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass

    async def dismiss_popups(self):
        """关闭页面弹窗"""
        try:
            await self.page.evaluate("""
                (() => {
                    document.querySelectorAll('[class*="modal"], [class*="dialog"], [class*="popup"]')
                        .forEach(el => { el.style.display = 'none'; });
                })()
            """)
        except Exception:
            pass


class TaskSubmitter:
    """负责向编辑器填入代码、提交并获取结果"""

    def __init__(self, browser_session: BrowserSession):
        self.bs = browser_session
        self.page = browser_session.page

    async def submit_code(self, task_url: str, code: str) -> dict:
        """完整提交流程: 导航 -> 填代码 -> 提交 -> 等结果"""
        await self._navigate_to_task(task_url)
        await self._fill_code_editor(code)
        await self._click_evaluate()
        result = await self._wait_for_result()
        return result

    async def wait_with_skip(self, delay: int):
        """等待指定秒数，按回车可跳过"""
        import sys

        mins, secs = divmod(delay, 60)
        print(f"[反检测] 等待 {mins}分{secs}秒 (按回车跳过)...", end="", flush=True)

        loop = asyncio.get_event_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, sys.stdin.readline),
                timeout=delay,
            )
            print(" 跳过!")
        except asyncio.TimeoutError:
            print()
            print("[反检测] 等待结束，自动继续")

    async def _navigate_to_task(self, task_url: str):
        """导航到题目页面"""
        await self.page.goto(task_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # 关闭可能的弹窗
        close_btns = self.page.locator('[class*="close"], [class*="modal"] button')
        try:
            count = await close_btns.count()
            for i in range(min(count, 3)):
                try:
                    await close_btns.nth(i).click(timeout=2000)
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
        except Exception:
            pass

    async def _fill_code_editor(self, code: str):
        """向代码编辑器填入代码（清空+填入一体）"""
        await asyncio.sleep(2)

        escaped_code = code.replace("\\", "\\\\").replace("`", "\\`")

        # 1. Monaco API (setValue 直接替换全部内容)
        if await self._try_monaco(escaped_code):
            return

        # 2. CodeMirror API (setValue 直接替换全部内容)
        if await self._try_codemirror(escaped_code):
            return

        # 3. 剪贴板粘贴（保留格式和缩进）
        if await self._paste_code(code):
            return

        # 4. Textarea 兜底
        if await self._try_textarea(code):
            return

        raise Exception("无法定位代码编辑器，请检查页面")

    async def _paste_code(self, code: str) -> bool:
        """通过剪贴板粘贴代码，保留所有格式和缩进"""
        # 写入剪贴板
        try:
            await self.page.evaluate(f"""
                navigator.clipboard.writeText(`{code.replace('`', '\\`')}`)
            """)
        except Exception:
            return False
        await asyncio.sleep(0.3)

        # 聚焦编辑器并粘贴
        selectors = [
            ".monaco-editor",
            ".monaco-editor textarea",
            ".monaco-editor .inputarea",
            ".CodeMirror",
            ".CodeMirror textarea",
            ".CodeMirror-code",
            ".ace_editor",
            ".ace_text-input",
            '[class*="code-editor"]',
            '[class*="code-editor"] textarea',
            '[class*="editor-pane"]',
            '[class*="editor-pane"] textarea',
            'textarea[class*="code"]',
            'textarea[class*="editor"]',
            'textarea',
        ]
        for sel in selectors:
            try:
                el = self.page.locator(sel).first
                if not await el.is_visible(timeout=1000):
                    continue

                await el.click()
                await asyncio.sleep(0.3)

                # 全选删除
                await self.page.keyboard.press("Control+a")
                await asyncio.sleep(0.2)
                await self.page.keyboard.press("Delete")
                await asyncio.sleep(0.2)

                # 粘贴（保留原始格式和缩进）
                await self.page.keyboard.press("Control+v")
                await asyncio.sleep(0.3)
                return True
            except Exception:
                continue
        return False

    async def _try_monaco(self, code: str) -> bool:
        js = f"""
        (() => {{
            try {{
                const editors = window.monaco?.editor?.getEditors?.();
                if (editors && editors.length > 0) {{
                    editors[0].setValue(`{code}`);
                    return true;
                }}
            }} catch(e) {{}}
            return false;
        }})()
        """
        try:
            return bool(await self.page.evaluate(js))
        except Exception:
            return False

    async def _try_codemirror(self, code: str) -> bool:
        js = f"""
        (() => {{
            try {{
                const cmEls = document.querySelectorAll('.CodeMirror');
                for (const el of cmEls) {{
                    if (el.CodeMirror) {{
                        el.CodeMirror.setValue(`{code}`);
                        return true;
                    }}
                }}
            }} catch(e) {{}}
            return false;
        }})()
        """
        try:
            return bool(await self.page.evaluate(js))
        except Exception:
            return False

    async def _try_textarea(self, code: str) -> bool:
        selectors = [
            'textarea[class*="code"]',
            'textarea[class*="editor"]',
            ".ace_text-input",
            "textarea",
        ]
        for selector in selectors:
            try:
                ta = self.page.locator(selector).first
                if await ta.is_visible():
                    await ta.click()
                    await ta.fill(code)
                    return True
            except Exception:
                continue
        return False

    async def _click_evaluate(self):
        """点击评测按钮"""
        eval_selectors = [
            'button:has-text("评测")',
            'button:has-text("提交运行")',
            'button:has-text("提交")',
            'button:has-text("运行")',
            'a:has-text("评测")',
            '[class*="evaluate-btn"]',
            '[class*="submit-btn"]',
        ]
        for selector in eval_selectors:
            try:
                btn = self.page.locator(selector).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    return
            except Exception:
                continue
        raise Exception("找不到评测按钮，请手动检查页面")

    async def _wait_for_result(self) -> dict:
        """等待评测结果"""
        start = time.time()
        deadline = start + EVALUATE_TIMEOUT / 1000
        previous_body_len = 0

        while time.time() < deadline:
            await asyncio.sleep(2)

            try:
                result = await self._extract_result()
                if result["status"] in ("pass", "fail", "error"):
                    return result
            except Exception:
                pass

            # 检查页面是否有变化（新内容出现）
            try:
                body_len = await self.page.evaluate("document.body?.innerText?.length || 0")
                if body_len != previous_body_len:
                    previous_body_len = body_len
            except Exception:
                pass

        # 超时：做最后一次检查，捕获页面所有可见文字
        try:
            last_check = await self.page.evaluate("""
                (() => {
                    const body = document.body?.innerText || '';
                    return body.substring(Math.max(0, body.length - 2000));
                })()
            """)
        except Exception:
            last_check = "无法读取页面"

        return {
            "status": "timeout",
            "text": f"等待超时。页面末尾内容:\n{last_check[:1000]}",
            "success": False,
        }

    async def _extract_result(self) -> dict:
        js = """
        (() => {
            // 扩大查找范围，检查更多元素
            const allElements = document.querySelectorAll(
                '[class*="result"], [class*="evaluate"], [class*="test"], '
                + '[class*="output"], [class*="feedback"], [class*="score"], '
                + '[class*="pass"], [class*="fail"], [class*="success"], '
                + '[class*="error"], [class*="message"], [class*="alert"], '
                + '[class*="notification"], [class*="toast"], '
                + '.ant-alert, .ant-message, .ant-notification, .ant-result'
            );
            let best = {text: '', score: 0};

            for (const el of allElements) {
                if (!el.offsetParent) continue; // skip hidden
                const text = el.innerText?.trim() || '';

                // 评分：优先找有明显结果关键词的
                let score = 0;
                if (text.includes('通过') || text.includes('正确') || text.includes('恭喜')) score = 100;
                else if (text.includes('错误') || text.includes('失败') || text.includes('不通过')) score = 80;
                else if (text.match(/得分|成绩|score/i)) score = 60;
                else if (text.match(/测试|test/i)) score = 40;
                else if (text.length > 20) score = 20;

                if (score > best.score) {
                    best = {text: text.substring(0, 2000), score: score};
                }
            }

            if (best.score > 0) {
                const t = best.text;
                const passed = (t.includes('通过') && !t.includes('未通过'))
                    || t.includes('正确') || t.includes('恭喜')
                    || t.includes('congratulations') || t.includes('success')
                    || t.includes('passed');
                const failed = t.includes('错误') || t.includes('失败')
                    || t.includes('不通过') || t.includes('error')
                    || t.includes('fail') || t.includes('未通过');
                return {
                    status: passed ? 'pass' : (failed ? 'fail' : 'pending'),
                    text: t,
                    success: passed
                };
            }
            return {status: 'pending', text: '', success: false};
        })()
        """
        try:
            result = await self.page.evaluate(js)
            return result
        except Exception:
            return {"status": "pending", "text": "", "success": False}

    async def click_next_task(self) -> str | None:
        """点击'下一题'按钮，返回新题目 URL，没有则返回 None"""
        old_url = self.page.url
        await asyncio.sleep(2)

        # 关闭弹窗
        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
            close_btn = self.page.locator('[class*="close"], [class*="modal"] button:has-text("关闭"), .ant-modal-close')
            if await close_btn.first.is_visible(timeout=1000):
                await close_btn.first.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass

        selectors = [
            'button:has-text("下一题")',
            'button:has-text("下一关")',
            'a:has-text("下一题")',
            'a:has-text("下一关")',
            '[class*="next"]',
            'button:has-text("Next")',
        ]
        for sel in selectors:
            try:
                btn = self.page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await asyncio.sleep(3)
                    new_url = self.page.url
                    if new_url and new_url != old_url:
                        return new_url
            except Exception:
                continue
        return None

    async def click_prev_task(self) -> str | None:
        """点击'上一题'按钮，返回上一题 URL，没有则返回 None"""
        old_url = self.page.url
        selectors = [
            'button:has-text("上一题")',
            'button:has-text("上一关")',
            'a:has-text("上一题")',
            'a:has-text("上一关")',
            '[class*="prev"]',
            '[class*="previous"]',
            'button:has-text("Prev")',
            'button:has-text("上一步")',
            '[class*="step"] button:has-text("上")',
            'button:has-text("上")',
            'a:has-text("上")',
            '[aria-label*="上一"]',
        ]
        for sel in selectors:
            try:
                btn = self.page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    await asyncio.sleep(3)
                    new_url = self.page.url
                    if new_url and new_url != old_url:
                        return new_url
            except Exception:
                continue
        return None

    async def is_current_passed(self) -> bool:
        """检查当前页面的题目是否已通过"""
        result = await self._extract_result()
        return result.get("status") == "pass"
        """导航到题目页面并检查是否已通过评测"""
        try:
            await self.page.goto(task_url, wait_until="domcontentloaded")
            await asyncio.sleep(3)
            result = await self._extract_result()
            return result.get("status") == "pass"
        except Exception:
            return False
