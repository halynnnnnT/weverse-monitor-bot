"""
取得 LINE 群組 ID 工具
=====================
使用方式：
  1. 將此檔案放到 /home/ubuntu/linebot/get_line_id.py
  2. 啟動此腳本（會暫時佔用 Port 5000）
  3. 在 LINE Developers Console 將 Webhook URL 指向此腳本
  4. 在群組裡發任意一則訊息
  5. Terminal 會印出群組 ID，記錄後 Ctrl+C 停止
"""

import os
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    JoinEvent,
)

# =====================
# 設定（與 linebot_monitor.py 相同的金鑰）
# =====================
LINE_CHANNEL_SECRET       = os.environ.get("LINE_CHANNEL_SECRET", "your_channel_secret")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "your_access_token")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler       = WebhookHandler(LINE_CHANNEL_SECRET)
app           = Flask(__name__)


# =====================
# Webhook 接收端點
# =====================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body      = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


# =====================
# Bot 加入群組時觸發（最可靠的取得時機）
# =====================
@handler.add(JoinEvent)
def handle_join(event: JoinEvent):
    source_type = event.source.type  # "group" 或 "room"

    if source_type == "group":
        group_id = event.source.group_id
        print("\n" + "=" * 50)
        print(f"✅ Bot 已加入群組！")
        print(f"   Source Type : {source_type}")
        print(f"   GROUP ID    : {group_id}")
        print("=" * 50 + "\n")
        print(f"請將以下值設定為環境變數 LINE_TARGET_ID：")
        print(f"  export LINE_TARGET_ID=\"{group_id}\"")
        print()

        # 同時回覆到群組，方便直接複製
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text=(
                                f"✅ 成功取得群組 ID！\n\n"
                                f"GROUP ID：\n{group_id}\n\n"
                                f"請複製上方 ID 並設定為 LINE_TARGET_ID 環境變數。"
                            )
                        )
                    ],
                )
            )

    elif source_type == "room":
        room_id = event.source.room_id
        print("\n" + "=" * 50)
        print(f"✅ Bot 已加入聊天室！")
        print(f"   Source Type : {source_type}")
        print(f"   ROOM ID     : {room_id}")
        print("=" * 50 + "\n")


# =====================
# 收到任何訊息時也印出 ID（備用）
# =====================
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    source_type = event.source.type

    if source_type == "group":
        group_id = event.source.group_id
        user_id  = event.source.user_id
        print("\n" + "=" * 50)
        print(f"📨 收到群組訊息")
        print(f"   Source Type : {source_type}")
        print(f"   GROUP ID    : {group_id}")
        print(f"   User ID     : {user_id}")
        print(f"   訊息內容    : {event.message.text}")
        print("=" * 50 + "\n")
        print(f"請將以下值設定為環境變數 LINE_TARGET_ID：")
        print(f"  export LINE_TARGET_ID=\"{group_id}\"")
        print()

    elif source_type == "user":
        user_id = event.source.user_id
        print("\n" + "=" * 50)
        print(f"📨 收到個人訊息")
        print(f"   Source Type : {source_type}")
        print(f"   USER ID     : {user_id}")
        print(f"   訊息內容    : {event.message.text}")
        print("=" * 50 + "\n")
        print(f"請將以下值設定為環境變數 LINE_TARGET_ID：")
        print(f"  export LINE_TARGET_ID=\"{user_id}\"")
        print()

    elif source_type == "room":
        room_id = event.source.room_id
        print("\n" + "=" * 50)
        print(f"📨 收到聊天室訊息")
        print(f"   Source Type : {source_type}")
        print(f"   ROOM ID     : {room_id}")
        print("=" * 50 + "\n")


# =====================
# 主程式
# =====================
if __name__ == "__main__":
    print("=" * 50)
    print("🔍 LINE ID 取得工具已啟動")
    print()
    print("步驟：")
    print("  1. 確認 ngrok 正在執行：ngrok http 5000")
    print("  2. 將 ngrok 的 HTTPS 網址設為 LINE Webhook URL")
    print("     例如：https://xxxx.ngrok-free.app/callback")
    print("  3. 將 Bot 邀請進群組，或在群組 / 個人聊天發任意訊息")
    print("  4. Terminal 會印出對應的 ID")
    print("  5. 取得 ID 後按 Ctrl+C 停止此腳本")
    print("     再啟動正式的 linebot_monitor.py")
    print("=" * 50 + "\n")

    app.run(host="0.0.0.0", port=5000, debug=False)
