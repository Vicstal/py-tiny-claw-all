# internal/feishu/bot.py
# 对应 Go 版: internal/feishu/bot.go
# 第 9 章：飞书机器人 —— 接收群聊消息事件，触发 Agent 运行，并把过程回报到群里。
# 使用飞书官方 Python SDK: lark-oapi (对应 Go 版的 larksuite/oapi-sdk-go)
#
# 一条消息的完整旅程：
#   1. 用户在飞书发消息
#   2. 飞书通过长连接把"收到消息"事件推给本机 -> on_message_receive 被调用
#   3. on_message_receive 取出文字，开一个后台线程跑 handle_agent_run
#   4. handle_agent_run 调用 engine.run(prompt, reporter)，Agent 开始干活
#   5. 引擎每到关键节点就调用 FeishuReporter.on_xxx -> send_msg -> 消息回到飞书
import json
import logging
import os
import re
import sys
import threading

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    P2ImMessageReceiveV1,
)

from internal.engine.loop import AgentEngine
from internal.engine.reporter import Reporter

log = logging.getLogger(__name__)


class FeishuBot:
    """飞书机器人"接收端"：负责听消息、把消息交给引擎去跑。"""

    def __init__(self, eng: AgentEngine):
        """初始化：读取飞书凭证，创建一个用于调用飞书 OpenAPI 的客户端。
        eng: 已经装配好 Provider 和工具的 Agent 引擎，所有消息共用这一个引擎。"""
        # 从环境变量读取应用凭证（在飞书开发者后台「凭证与基础信息」里获取）
        app_id = os.getenv("FEISHU_APP_ID")
        app_secret = os.getenv("FEISHU_APP_SECRET")

        if not app_id or not app_secret:
            sys.exit("请设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")

        # lark.Client 是调用飞书 API 的"遥控器"，比如后面用它发消息。
        # SDK 会用 app_id/app_secret 自动换取并刷新访问令牌（tenant_access_token）。
        client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()

        self.client = client
        self.app_id = app_id
        self.app_secret = app_secret
        self.engine = eng

    def get_event_dispatcher(self) -> lark.EventDispatcherHandler:
        """创建"事件分发器"：告诉 SDK 收到哪种事件时该调用哪个函数。
        这里只注册了一种事件 —— 收到消息（im.message.receive_v1）。
        返回的分发器会交给 main.py 里的长连接客户端使用。"""
        # 长连接模式下飞书不做加密/验签，这两个值留空即可
        encrypt_key = os.getenv("FEISHU_ENCRYPT_KEY", "")
        verify_token = os.getenv("FEISHU_VERIFY_TOKEN", "")

        def on_message_receive(event: P2ImMessageReceiveV1) -> None:
            """每当有人给机器人发消息（私聊或群里 @ 它），SDK 就会调用这个函数。
            event 里装着消息的全部信息：发送者、会话 ID、消息内容等。"""
            message = event.event.message
            # 图片、文件、表情等非文本消息直接忽略
            if message.message_type != "text":
                log.info("[Feishu] 忽略非文本消息: %s", message.message_type)
                return

            # 消息内容形如 {"text":"用户输入"}，用 json 解析比字符串剥壳更稳
            content_str = json.loads(message.content).get("text", "")
            # 群聊 @机器人 时文本里会带 @_user_1 这样的占位符，去掉
            content_str = re.sub(r"@_user_\d+", "", content_str).strip()

            # chat_id 标识"是哪个会话"（某个私聊或某个群），回消息时要用它
            chat_id = message.chat_id
            log.info("[Feishu] 收到会话 %s 消息: %s", chat_id, content_str)

            # 后台线程运行 Agent（对应 Go 版的 go b.handleAgentRun），
            # 避免阻塞事件回调导致飞书侧超时重推。
            # Agent 一跑可能几十秒，如果在这里直接跑，SDK 就卡住收不了下一条消息；
            # 开线程后本函数立刻返回，多条消息可以同时各跑各的。
            threading.Thread(
                target=self.handle_agent_run, args=(chat_id, content_str), daemon=True
            ).start()

        # builder 模式：创建分发器 -> 注册"收到消息"的处理函数 -> 构建完成
        handler = (
            lark.EventDispatcherHandler.builder(encrypt_key, verify_token)
            .register_p2_im_message_receive_v1(on_message_receive)
            .build()
        )

        return handler

    def handle_agent_run(self, chat_id: str, prompt: str):
        """在后台线程里真正运行 Agent。
        chat_id: 消息来自哪个会话，Agent 的所有汇报都发回这里
        prompt:  用户发来的文字，作为本次任务交给引擎"""
        # 每条消息新建一个 Reporter，绑定到对应会话，保证不同会话的回复不会串
        reporter = FeishuReporter(client=self.client, chat_id=chat_id)

        try:
            self.engine.run(prompt, reporter)
        except Exception as e:
            # 引擎出错（如模型 API 调用失败）时，把错误发到飞书，而不是只在终端默默报错
            reporter.send_msg(f"❌ Agent 运行崩溃: {e}")


class FeishuReporter(Reporter):
    """把引擎的关键事件转发到飞书群聊（实现 engine.Reporter 接口）
    是飞书机器人的"发送端"：引擎调用 on_xxx，它就把对应文字发到飞书。"""

    def __init__(self, client: lark.Client, chat_id: str):
        """client:  飞书 API 客户端（从 FeishuBot 传进来共用）
        chat_id: 要把消息发到哪个会话"""
        self.client = client
        self.chat_id = chat_id

    def send_msg(self, text: str):
        """调用飞书「发送消息」API，把一段纯文本发到 self.chat_id 对应的会话。
        下面 4 个 on_xxx 方法最终都调用它。"""
        # 飞书要求 content 是 JSON 字符串，如 {"text": "你好"}；
        # ensure_ascii=False 让中文保持原样，而不是变成 你好
        text_content = {"text": text}
        content_str = json.dumps(text_content, ensure_ascii=False)

        # 组装请求：
        #   receive_id_type("chat_id") —— 告诉飞书下面的 receive_id 是一个会话 ID
        #   receive_id / msg_type / content —— 发给谁、消息类型、消息内容
        msg_req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(self.chat_id)
                .msg_type("text")
                .content(content_str)
                .build()
            )
            .build()
        )

        # 真正发出请求；失败时（如权限没开、chat_id 不对）在终端打印原因
        resp = self.client.im.v1.message.create(msg_req)
        if not resp.success():
            log.error("[Feishu] 发送消息失败: code=%s msg=%s", resp.code, resp.msg)

    def on_thinking(self):
        """引擎进入慢思考阶段 -> 发一条"正在思考"提示。"""
        self.send_msg("🤔 模型正在慢思考 (Thinking)...")

    def on_tool_call(self, tool_name: str, args: str):
        """引擎即将执行工具 -> 告诉用户执行的是哪个工具、参数是什么。"""
        self.send_msg(f"🛠️ 正在执行工具: {tool_name}\n参数: {args}")

    def on_tool_result(self, tool_name: str, result: str, is_error: bool):
        """工具执行完毕 -> 失败时把错误内容发出来；成功时只报"成功"，不刷屏。"""
        if is_error:
            self.send_msg(f"⚠️ 执行报错 ({tool_name}): \n{result}")
        else:
            self.send_msg(f"✅ 执行成功 ({tool_name})")

    def on_message(self, content: str):
        """模型给出了文字回复 -> 原样转发给用户。"""
        self.send_msg(content)
