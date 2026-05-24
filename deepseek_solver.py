"""DeepSeek 求解器 - 发送题目到 chat.deepseek.com，点击"复制"按钮获取代码

首次使用需在 DeepSeek 登录（手机验证码），后续自动复用登录态。
"""

import asyncio
from playwright.async_api import Page

DEEPSEEK_URL = "https://chat.deepseek.com/"


class DeepSeekSolver:
    """通过 DeepSeek 聊天生成解题代码"""

    def __init__(self, page: Page):
        self.page = page
        self.ready = False

    async def init(self, wait_for_login: bool = True):
        """打开 DeepSeek，如需登录则轮询等待"""
        await self.page.goto(DEEPSEEK_URL, wait_until="domcontentloaded")
        await asyncio.sleep(4)

        if await self._is_chat_ready():
            self.ready = True
            print("[DeepSeek] 已登录，对话就绪")
            return

        if not wait_for_login:
            self.ready = True
            return

        print("\n[DeepSeek] 请在弹出的浏览器中完成登录（手机验证码）")
        print("[DeepSeek] 等待登录...", end="", flush=True)

        for i in range(120):
            await asyncio.sleep(2)
            print(".", end="", flush=True)
            try:
                if await self._is_chat_ready():
                    print(" 完成!")
                    await asyncio.sleep(2)
                    self.ready = True
                    return
            except Exception:
                pass
            if i % 5 == 0:
                await self._try_start_chat()

        print("\n[DeepSeek] 登录超时")
        self.ready = True

    async def _is_chat_ready(self) -> bool:
        return await self.page.evaluate("""
            (() => {
                const hasTextarea = !!document.querySelector('textarea');
                const noLoginBtn = !document.body.innerText.includes('登录');
                return hasTextarea && noLoginBtn;
            })()
        """)

    async def _try_start_chat(self):
        try:
            btns = await self.page.locator("button, a").all()
            for btn in btns:
                try:
                    text = (await btn.inner_text()).strip()
                    if text in ("开始对话", "新建对话", "New Chat", "开始"):
                        await btn.click()
                        await asyncio.sleep(2)
                        return
                except Exception:
                    pass
        except Exception:
            pass

    async def solve(self, problem_desc: str, language: str = "python") -> str:
        """发送题目，等待回复，点击"复制"按钮获取代码"""
        if not self.ready:
            await self.init()

        prompt = self._build_prompt(problem_desc, language)
        await self._ensure_new_chat()

        print("[DeepSeek] 发送题目...")
        await self._send_message(prompt)

        print("[DeepSeek] 等待回复...")
        await self._wait_for_response()

        code = await self._copy_code_via_clipboard()
        if code:
            print(f"[DeepSeek] 复制到代码 ({len(code)} 字符)")
        else:
            print("[DeepSeek] 未找到复制按钮，尝试 HTML 提取...")
            code = await self._extract_from_pre()
            if code:
                print(f"[DeepSeek] HTML 提取到代码 ({len(code)} 字符)")
            else:
                print("[DeepSeek] 未提取到代码")
        return code

    def _build_prompt(self, problem_desc: str, language: str = "python") -> str:
        return (
            f"请根据以下题目要求写出{language}代码。\n\n"
            f"## 题目\n{problem_desc}\n\n"
            f"## 要求\n"
            f"1. 只输出代码，不要任何解释说明\n"
            f"2. 代码必须直接可运行，不要用 if __name__ == '__main__'，直接在顶层写逻辑\n"
            f"3. 使用 input() 读入，print() 输出\n"
            f"4. 注意边界条件\n"
            f"5. 用 markdown 代码块格式输出"
        )

    async def _ensure_new_chat(self):
        has_textarea = await self.page.evaluate("!!document.querySelector('textarea')")
        if has_textarea:
            return
        try:
            btn = self.page.locator(
                '[class*="new-chat"], [class*="new_conversation"], '
                'button:has-text("新"), [class*="sidebar"] button'
            ).first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                await asyncio.sleep(2)
        except Exception:
            pass

    async def _send_message(self, text: str):
        ta = self.page.locator("textarea").first
        await ta.wait_for(state="visible", timeout=15000)
        await ta.click()
        await asyncio.sleep(0.3)
        await ta.fill(text)
        await asyncio.sleep(1)
        await ta.press("Enter")
        await asyncio.sleep(2)

        val = await ta.input_value()
        if val and len(val) > 0:
            await self._click_send_button()

    async def _click_send_button(self):
        try:
            btns = self.page.locator("button:has(svg)")
            count = await btns.count()
            for i in range(count):
                btn = btns.nth(i)
                try:
                    if not await btn.is_visible(timeout=1000):
                        continue
                    disabled = await btn.get_attribute("disabled")
                    if disabled is not None:
                        continue
                    await btn.click()
                    return
                except Exception:
                    continue
        except Exception:
            pass
        await self.page.keyboard.press("Control+Enter")

    async def _wait_for_response(self, timeout: int = 180):
        """等待 '停止' 按钮消失 = 生成完成"""
        for _ in range(timeout):
            await asyncio.sleep(2)
            still_loading = await self.page.evaluate("""
                (() => {
                    const allBtns = document.querySelectorAll('button');
                    for (const b of allBtns) {
                        if (b.innerText?.includes('停止') && b.offsetParent !== null)
                            return true;
                    }
                    return false;
                })()
            """)
            if not still_loading:
                await asyncio.sleep(3)
                return

    async def _copy_code_via_clipboard(self) -> str:
        """点击最后一个'复制'按钮，读剪贴板获取代码"""
        for attempt in range(15):
            has_btn = await self.page.evaluate("""
                (() => {
                    const btns = document.querySelectorAll('button, [role="button"], span');
                    for (const b of btns) {
                        if (b.innerText?.trim() === '复制' && b.offsetParent !== null)
                            return true;
                    }
                    return false;
                })()
            """)
            if has_btn:
                break
            await asyncio.sleep(1)

        if not has_btn:
            return ""

        clicked = await self.page.evaluate("""
            (() => {
                const btns = document.querySelectorAll('button, [role="button"], span');
                let last = null;
                for (const b of btns) {
                    if (b.innerText?.trim() === '复制' && b.offsetParent !== null)
                        last = b;
                }
                if (last) { last.click(); return true; }
                return false;
            })()
        """)

        if not clicked:
            return ""

        await asyncio.sleep(0.5)
        try:
            code = await self.page.evaluate("() => navigator.clipboard.readText()")
            if code and len(code) > 15:
                return code.strip()
        except Exception:
            pass

        return ""

    async def _extract_from_pre(self) -> str:
        """从 <pre> 元素提取代码（备用方案）"""
        for attempt in range(10):
            code = await self.page.evaluate("""
                (() => {
                    const pres = document.querySelectorAll('pre');
                    for (let i = pres.length - 1; i >= 0; i--) {
                        const text = pres[i].innerText || '';
                        if (text.length > 15) return text;
                    }
                    return '';
                })()
            """)
            if code:
                return code.strip()
            await asyncio.sleep(1)
        return ""
