"""EduCoder 题目读取模块 - 通过 Playwright 从页面提取题目信息"""

import re
import asyncio


class ProblemInfo:
    """题目信息数据结构"""
    def __init__(self):
        self.task_id: str = ""
        self.title: str = ""
        self.description: str = ""
        self.language: str = "python"
        self.code_template: str = ""
        self.url: str = ""


class ProblemReader:
    """通过浏览器页面提取题目信息"""

    # 支持多种 URL 格式
    URL_PATTERNS = [
        # 完整URL: https://www.educoder.net/tasks/HB6K5P4B/3492057/smk37gf6tel5
        r"https?://(?:www\.)?educoder\.net/tasks/[^/\s]+(?:/[^/\s]+(?:/[^/\s]+)?)?",
        r"https?://(?:www\.)?educoder\.net/shixuns/[^/\s]+(?:/[^/\s]+(?:/[^/\s]+)?)?",
    ]

    @staticmethod
    def is_url(user_input: str) -> bool:
        user_input = user_input.strip()
        for pattern in ProblemReader.URL_PATTERNS:
            if re.match(pattern, user_input):
                return True
        return False

    @staticmethod
    def normalize_url(user_input: str) -> str:
        """标准化用户输入的 URL"""
        user_input = user_input.strip()
        # 如果已经是完整 URL
        if user_input.startswith("http"):
            for pattern in ProblemReader.URL_PATTERNS:
                m = re.match(pattern, user_input)
                if m:
                    return m.group(0)
            return user_input

        raise ValueError(
            f"无法解析输入。请提供完整 URL，例如:\n"
            "  https://www.educoder.net/tasks/xxxxx/xxxxx/xxxxx"
        )

    async def read_from_page(self, page, task_url: str) -> ProblemInfo:
        """通过 Playwright 页面读取题目信息"""
        info = ProblemInfo()
        info.url = task_url

        # 导航到题目页面
        await page.goto(task_url, wait_until="domcontentloaded")
        await asyncio.sleep(4)  # 等待 JS 渲染完成

        # 关闭可能的弹窗
        await self._dismiss_popups(page)

        # 从页面提取信息
        info.title = await self._extract_title(page)
        info.description = await self._extract_description(page)
        info.language = await self._extract_language(page)
        info.code_template = await self._extract_code_template(page)
        info.task_id = task_url

        return info

    async def _dismiss_popups(self, page):
        """关闭页面弹窗"""
        try:
            await page.evaluate("""
                document.querySelectorAll('[class*="modal"], [class*="dialog"], [class*="popup"]')
                    .forEach(el => { if(el.style.display !== 'none') el.style.display = 'none'; });
            """)
        except Exception:
            pass

    async def _extract_title(self, page) -> str:
        """从页面提取标题"""
        js = """
        (() => {
            const selectors = [
                '[class*="task-title"]', '[class*="shixun-title"]',
                '[class*="challenge-title"]', '[class*="header-title"]',
                'h1', 'h2', 'h3',
                '.title', '[class*="title"]',
                '.ant-page-header-heading-title',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText && el.innerText.trim().length > 1) {
                    return el.innerText.trim().split('\\n')[0].substring(0, 200);
                }
            }
            return document.title || '';
        })()
        """
        try:
            title = await page.evaluate(js)
            return title or "未知题目"
        except Exception:
            return "未知题目"

    async def _extract_description(self, page) -> str:
        """从页面提取题目描述（排除代码编辑器内容）"""
        js = """
        (() => {
            // 先尝试专用的题目描述区域
            const descSelectors = [
                '[class*="task-desc"]', '[class*="challenge-desc"]',
                '[class*="question-desc"]', '[class*="problem-desc"]',
                '[class*="description"]',
                '.markdown-body', '[class*="markdown"]',
                '.ant-descriptions',
            ];
            for (const sel of descSelectors) {
                const el = document.querySelector(sel);
                if (el) {
                    const t = el.innerText?.trim();
                    if (t && t.length > 50) return t.substring(0, 5000);
                }
            }

            // 降级: 获取不含代码的页面文字
            // 排除编辑器区域
            const excludeSel = [
                '.monaco-editor', '.CodeMirror', '.ace_editor',
                '[class*="code-editor"]', '[class*="editor-pane"]',
                'textarea', '[class*="monaco"]',
            ];
            const clone = document.body.cloneNode(true);
            for (const sel of excludeSel) {
                clone.querySelectorAll(sel).forEach(e => e.remove());
            }
            // 也排除脚本和样式
            clone.querySelectorAll('script, style, nav, header, footer').forEach(e => e.remove());

            const text = clone.innerText?.trim() || '';
            // 清理多余空白
            const cleaned = text.replace(/\\n{3,}/g, '\\n\\n').substring(0, 5000);
            return cleaned;
        })()
        """
        try:
            desc = await page.evaluate(js)
            return desc or ""
        except Exception:
            return ""

    async def _extract_language(self, page) -> str:
        """检测编程语言"""
        js = """
        (() => {
            const selectors = [
                '[class*="language"]', '[class*="lang"]',
                '[data-language]',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                const lang = el?.getAttribute?.('data-language') ||
                             el?.innerText?.trim()?.toLowerCase();
                if (lang && lang.includes('python')) return 'python';
                if (lang && lang.includes('java')) return 'java';
                if (lang && lang.includes('c++')) return 'cpp';
            }
            // 检查页面文本
            const body = document.body?.innerText || '';
            if (body.includes('Python') || body.includes('python')) return 'python';
            return 'python';
        })()
        """
        try:
            return await page.evaluate(js)
        except Exception:
            return "python"

    async def _extract_code_template(self, page) -> str:
        """从编辑器提取初始代码模板"""
        js = """
        (() => {
            // Monaco Editor
            if (window.monaco?.editor?.getEditors) {
                const editors = window.monaco.editor.getEditors();
                if (editors.length > 0) return editors[0].getValue() || '';
            }
            // CodeMirror
            const cmEls = document.querySelectorAll('.CodeMirror');
            for (const el of cmEls) {
                if (el.CodeMirror) return el.CodeMirror.getValue() || '';
            }
            // 普通 textarea
            const ta = document.querySelector('textarea[class*="code"], textarea[class*="editor"]');
            if (ta) return ta.value || '';
            // .ace_editor (ACE Editor)
            if (window.ace) {
                const aceEditor = window.ace.edit(document.querySelector('.ace_editor'));
                if (aceEditor) return aceEditor.getValue() || '';
            }
            return '';
        })()
        """
        try:
            return await page.evaluate(js)
        except Exception:
            return ""
