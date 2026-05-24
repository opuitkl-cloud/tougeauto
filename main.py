"""EduCoder 自动做题 - Python编程题 x DeepSeek 解答

用法:
    python main.py                     # 交互模式（输入 URL）
    python main.py <题目URL>           # 直接运行（全自动）
    python main.py --headless <URL>    # 无头模式
"""

import sys
import os
import random
import logging
import asyncio
import argparse
from problem_reader import ProblemReader, ProblemInfo
from deepseek_solver import DeepSeekSolver
from task_submitter import BrowserSession, TaskSubmitter
from config import BROWSER_TIMEOUT, LOG_FILE

log = logging.getLogger("educoder")


def setup_logging():
    log_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(log_dir, LOG_FILE)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        filename=log_path,
        encoding="utf-8",
        filemode="a",
    )
    return log_path


def print_banner():
    print("=" * 60)
    print("  EduCoder 自动做题 - Python编程题 x DeepSeek 解答")
    print("=" * 60)


def print_problem(info: ProblemInfo):
    desc = info.description or "(无)"
    if len(desc) > 300:
        desc = desc[:300] + "..."
    print(f"\n[题目] {info.title}")
    print(f"[描述] {desc}")
    log.info("题目: %s", info.title)


async def run_loop(task_url: str):
    """从第一题开始逐题做题，已通过的跳过"""
    log.info("开始处理: %s", task_url)

    bs = BrowserSession()
    solver = None

    try:
        await bs.start()

        submitter = TaskSubmitter(bs)
        await submitter.page.goto(task_url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # 回到第一题
        print("\n[定位] 回到第一题...")
        while True:
            prev = await submitter.click_prev_task()
            if not prev:
                break
            print(f"  <- 上一题: {prev}")
        current_url = submitter.page.url
        print(f"[定位] 第一题: {current_url}")
        log.info("第一题: %s", current_url)

        # 逐题做题
        while current_url:
            print(f"\n{'='*60}")
            print(f"  当前题: {current_url}")
            print(f"{'='*60}")
            log.info("处理: %s", current_url)

            # 检查是否已通过
            print("\n[检查] 检测是否已通过...")
            if await submitter.is_current_passed():
                print("  已通过，跳过")
                log.info("已通过，跳过: %s", current_url)
                current_url = await submitter.click_next_task()
                if current_url:
                    print(f">>> 下一题: {current_url}")
                continue

            # 1. 读题
            print("\n[1/4] 读取题目...")
            reader = ProblemReader()
            info = await reader.read_from_page(bs.page, current_url)
            print_problem(info)

            if not info.description.strip():
                info.description = await bs.page.evaluate(
                    "document.body?.innerText?.substring(0, 5000) || ''"
                )

            # 2. DeepSeek 求解
            if solver is None:
                dp = await bs.context.new_page()
                dp.set_default_timeout(BROWSER_TIMEOUT)
                solver = DeepSeekSolver(dp)

            print("\n[2/4] DeepSeek 生成代码...")
            code = await solver.solve(info.description, info.language)

            if not code:
                print("[错误] 未能获取代码，终止")
                log.error("未能获取代码: %s", current_url)
                break

            print(f"\n[代码] ({len(code)} 字符)")
            print("-" * 40)
            print(code[:600] + ("..." if len(code) > 600 else ""))
            print("-" * 40)
            log.info("获取代码 %d 字符: %s", len(code), current_url)

            # 3. 提交
            print("\n[3/4] 提交到 EduCoder...")
            delay = random.randint(180, 540)
            await submitter.wait_with_skip(delay)
            result = await submitter.submit_code(current_url, code)

            # 4. 结果
            print("\n[4/4] 评测结果:")
            print("=" * 40)
            if result.get("success"):
                print("  通过!")
                log.info("通过: %s", current_url)
            elif result.get("status") == "fail":
                print("  未通过")
                log.info("未通过: %s", current_url)
            else:
                print(f"  {result.get('status', 'unknown')}")
                log.info("状态 %s: %s", result.get("status"), current_url)
            if result.get("text"):
                print(f"\n{result['text'][:1500]}")
                log.info("结果片段: %s", result["text"][:500])
            print("=" * 40)

            # 5. 下一题
            current_url = await submitter.click_next_task()
            if current_url:
                print(f"\n>>> 进入下一题: {current_url}")
                log.info("下一题: %s", current_url)
            else:
                print("\n[完成] 所有题目已处理完毕")

    finally:
        if solver and solver.page:
            await solver.page.close()
        await bs.close()


async def main():
    parser = argparse.ArgumentParser(description="EduCoder 自动做题程序")
    parser.add_argument("url", nargs="?", help="题目 URL")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    args = parser.parse_args()

    log_path = setup_logging()
    print_banner()
    print(f"[日志] {log_path}")
    print("[提示] 输入做题页面的网址\n")

    if args.url:
        await run_loop(args.url)
    else:
        while True:
            print("\n" + "-" * 50)
            try:
                u = input("题目 URL (q 退出): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见!")
                log.info("用户退出")
                break
            if u.lower() in ("q", "quit", "exit"):
                print("再见!")
                log.info("用户退出")
                break
            if u:
                await run_loop(u)


if __name__ == "__main__":
    asyncio.run(main())
