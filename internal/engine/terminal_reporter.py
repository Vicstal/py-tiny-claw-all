# internal/engine/terminal_reporter.py
# 对应 Go 版: internal/engine/terminal_reporter.go
# 第 10 章：终端版 Reporter —— 在本地调试时直接把过程打印到终端。
# （本项目提前到第 9 章引入：与 FeishuReporter 是同一个接口的两种实现，
#  不想连飞书时，在 main.py 里把 RUN_MODE 改成 "terminal" 即可本地调试。）
from internal.engine.reporter import Reporter


class TerminalReporter(Reporter):
    """把引擎的关键事件打印到终端（实现 engine.Reporter 接口）。
    和 FeishuReporter 的区别只在"发到哪"：一个 print，一个调用飞书 API。"""

    def on_thinking(self):
        """引擎进入慢思考阶段 -> 打印"思考中"提示。"""
        print("\n[🤔 思考中] 模型正在推理...")

    def on_tool_call(self, tool_name: str, args: str):
        """引擎即将执行工具 -> 打印工具名和参数。"""
        print(f"[🛠️ 调用工具] {tool_name}")
        # 清理参数中的换行符和特殊字符，让参数在终端里保持一行显示
        display_args = args.replace("\n", "\\n").replace("\r", "\\r")
        # 参数太长（比如 write_file 写一整个文件）时截断，避免刷屏
        if len(display_args) > 150:
            display_args = display_args[:150] + "... (已截断)"
        print(f"    参数: {display_args}")

    def on_tool_result(self, tool_name: str, result: str, is_error: bool):
        """工具执行完毕 -> 失败时打印错误内容；成功时只打印"成功"。"""
        if is_error:
            print(f"[❌ 执行失败] {tool_name}")
            # 显示错误信息
            if result != "":
                print(f"    错误: {result}")
        else:
            print(f"[✅ 执行成功] {tool_name}")

    def on_message(self, content: str):
        """模型给出了文字回复 -> 打印出来（空内容不打印）。"""
        if content == "":
            return
        print(f"\n🤖 Agent 回复:\n{content}\n")


def new_terminal_reporter() -> TerminalReporter:
    """对应 Go 版的 NewTerminalReporter 构造函数"""
    return TerminalReporter()
