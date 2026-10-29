# internal/engine/reporter.py
# 对应 Go 版: internal/engine/reporter.go
# 第 9 章：Reporter 接口 —— 把引擎运行过程中的关键事件外发（如飞书群、终端）。
#
# 为什么需要它？
#   引擎（loop.py）只负责"想 -> 调工具 -> 再想"，不关心结果显示在哪里。
#   它在关键时刻调用 reporter.on_xxx(...)，至于是打印到终端、发到飞书、
#   还是发到钉钉，由传进来的具体 Reporter 子类决定。
#   换一个输出渠道，只需要再写一个子类，引擎代码一行都不用改。
from abc import ABC, abstractmethod


class Reporter(ABC):
    """抽象基类（相当于 Go 的 interface）：只规定"要有哪些方法"，不写具体实现。
    子类必须把下面 4 个方法全部实现，否则无法实例化。"""

    @abstractmethod
    def on_thinking(self):
        """模型开始"慢思考"时调用（仅 enable_thinking=True 时触发）。
        用途：告诉用户"我在想，别着急"。"""
        ...

    @abstractmethod
    def on_tool_call(self, tool_name: str, args: str):
        """模型决定调用某个工具、即将执行之前调用。
        tool_name: 工具名，如 "read_file"、"bash"
        args:      模型给出的参数，原始 JSON 字符串，如 '{"path": "a.txt"}'"""
        ...

    @abstractmethod
    def on_tool_result(self, tool_name: str, result: str, is_error: bool):
        """工具执行完毕后调用。
        result:   工具输出（引擎已截断到 200 字左右，避免刷屏）
        is_error: 工具是否执行失败（如文件不存在、命令报错）"""
        ...

    @abstractmethod
    def on_message(self, content: str):
        """模型输出了一段要给用户看的文字（中间说明或最终回答）时调用。"""
        ...
