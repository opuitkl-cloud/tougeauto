# EduCoder 自动做题

通过 Playwright 操控浏览器，自动从 EduCoder 读取编程题、调用 DeepSeek 生成答案、提交评测，支持逐题自动完成。

## 工作原理

```
输入题目 URL → 回到第一题 → 逐题做题 →
  ① 读题（提取题目描述）
  ② DeepSeek 生成代码（打开 chat.deepseek.com 发送题目，点"复制"获取代码）
  ③ 等待随机时间（防检测，可回车跳过）
  ④ 填入编辑器并提交评测
  ⑤ 自动进入下一题
```

已通过的题目会自动跳过，不做重复提交。

## 环境要求

- Python 3.8+
- Windows
- Chrome / Chromium 浏览器

## 安装

```bash
pip install -r requirements.txt
playwright install chromium
```

## 使用

```bash
# 交互模式（输入 URL）
python main.py

# 直接指定题目 URL（全自动）
python main.py https://www.educoder.net/tasks/xxxxx

# 无头模式（不显示浏览器窗口）
python main.py --headless https://www.educoder.net/tasks/xxxxx
```

### 无头模式说明

有已保存的登录态时，启动前询问是否进入无头模式（无需重启浏览器）。
首次使用则先以可见窗口启动，登录后询问是否切换到无头模式。
加 `--headless` 参数可跳过询问，直接全程无头。

## 首次使用

1. 运行脚本后，浏览器会自动打开
2. 如果未登录 EduCoder，页面会跳转到登录页，**手动登录即可**
3. DeepSeek 同样需要首次手动登录（手机验证码）
4. 登录态会自动保存到 `browser_state.json`，下次运行无需再次登录

## 文件说明

| 文件 | 说明 |
|---|---|
| `main.py` | 入口文件 |
| `config.py` | 浏览器配置（无头模式、超时时间） |
| `task_submitter.py` | 浏览器管理、操作编辑器、评测提交 |
| `problem_reader.py` | 从页面提取题目描述 |
| `deepseek_solver.py` | 调用 DeepSeek 生成代码 |
| `browser_state.json` | 自动生成，浏览器登录态缓存（已 gitignore） |
| `educoder_auto.log` | 自动生成，运行日志（已 gitignore） |
