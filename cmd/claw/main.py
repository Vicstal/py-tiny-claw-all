# cmd/claw/main.py
# 对应 Go 版: cmd/claw/main.go
# 第 9 章：启动飞书机器人服务，把 Agent 接入群聊。
# 与教材不同：这里用飞书「长连接」(WebSocket) 接收事件，而不是 Webhook HTTP 服务，
# 由本机主动连上飞书开放平台，因此不需要公网 IP / ngrok。
# 运行方式：在 PyCharm 里直接运行本文件即可（环境变量在 ~/.zshrc 中配置）。
# 运行模式见下方 RUN_MODE：飞书机器人 / 本地终端对话，二选一。
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import lark_oapi as lark

from internal.engine.loop import AgentEngine
from internal.engine.terminal_reporter import new_terminal_reporter
from internal.feishu.bot import FeishuBot
from internal.provider.openai import new_deepseek_provider
from internal.tools.bash import BashTool
from internal.tools.edit_file import EditFileTool
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import new_registry
from internal.tools.write_file import WriteFileTool

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(message)s",
                    datefmt="%Y/%m/%d %H:%M:%S")
log = logging.getLogger(__name__)

# 运行模式：
#   "feishu"   —— 启动飞书机器人，在飞书里对话（需要 FEISHU_APP_ID / FEISHU_APP_SECRET）
#   "terminal" —— 不连飞书，直接在 PyCharm 控制台里输入问题，过程用 TerminalReporter 打印
RUN_MODE = "feishu"
# RUN_MODE = "terminal"



def run_terminal(eng: AgentEngine):
    """终端对话模式：循环读取输入，每句话跑一次引擎，输入 exit 退出。"""
    reporter = new_terminal_reporter()
    print("💻 终端模式已启动，输入你的问题（输入 exit 退出）")
    while True:
        try:
            prompt = input("\n👤 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if prompt in ("exit", "quit"):
            break
        if prompt == "":
            continue
        try:
            eng.run(prompt, reporter)
        except Exception as e:
            print(f"❌ Agent 运行崩溃: {e}")

"""
        飞书通过长连接推送 im.message.receive_v1 事件,
        程序通过长连接接收飞书消息，过程用 FeishuReporter 发回飞书。
"""
def run_feishu(eng: AgentEngine):
    bot = FeishuBot(eng)
    ws_client = lark.ws.Client(
        bot.app_id,
        bot.app_secret,
        event_handler=bot.get_event_dispatcher(),
        log_level=lark.LogLevel.INFO,
    )

    log.info("🚀 py-tiny-claw-all 飞书机器人已启动，正在通过长连接接收事件...")
    try:
        ws_client.start()  # 阻塞运行，断线会自动重连
    except Exception as e:
        sys.exit(f"飞书长连接启动失败: {e}")


def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        sys.exit("请先配置 DEEPSEEK_API_KEY 环境变量")

    work_dir = PROJECT_ROOT / "workspace"
    work_dir.mkdir(exist_ok=True)

    llm_provider = new_deepseek_provider("deepseek-v4-flash")
    registry = new_registry()
    registry.register(ReadFileTool(str(work_dir)))
    registry.register(WriteFileTool(str(work_dir)))
    registry.register(BashTool(str(work_dir)))
    registry.register(EditFileTool(str(work_dir)))

    # 为节省 token 关闭慢思考；想在飞书里看到 "🤔 慢思考" 提示可改为 True
    eng = AgentEngine(llm_provider, registry, str(work_dir), False)

    if RUN_MODE == "terminal":
        run_terminal(eng)
    else:
        run_feishu(eng)


if __name__ == "__main__":
    main()
