"""
Weverse Shop 商品監控 LINE Bot
情境一測試版：啟動時立即檢查商品狀態，若為 SALE 則發送通知
"""

import os
import json
import logging
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from apscheduler.schedulers.background import BackgroundScheduler
from urllib.parse import urlparse

# =====================
# 基本設定
# =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 從環境變數讀取 LINE 設定
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "your_channel_secret")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "your_access_token")
# 要推播通知的 LINE 群組 ID 或使用者 ID
LINE_TARGET_ID = os.environ.get("LINE_TARGET_ID", "your_group_or_user_id")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# =====================
# 商品追蹤狀態管理
# key: url, value: {"status": "SOLD_OUT" | "SALE" | ..., "name": "..."}
# =====================
tracked_items = {}  # key: url (str), value: {"status": str, "name": str}


# =====================
# 工具函式
# =====================

def fetch_product_info(url: str):
    """
    從 Weverse Shop 商品頁面取得商品名稱與庫存狀態。
    回傳 {"name": str, "status": str} 或 None（失敗時）
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"請求失敗 [{url}]: {e}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if not next_data_tag:
        logger.warning(f"找不到 __NEXT_DATA__ [{url}]")
        return None

    try:
        data = json.loads(next_data_tag.string)
        queries = data["props"]["pageProps"]["$dehydratedState"]["queries"]
        for query in queries:
            key = query.get("queryKey", [None])[0]
            if isinstance(key, str) and "sales/:saleId" in key:
                sale_data = query["state"]["data"]
                return {
                    "name": sale_data["name"],
                    "status": sale_data["status"],
                }
    except (KeyError, TypeError, json.JSONDecodeError) as e:
        logger.error(f"解析 JSON 失敗 [{url}]: {e}")

    return None


def send_line_message(text: str) -> None:
    """推播訊息到指定的 LINE 群組或使用者"""
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.push_message(
            PushMessageRequest(
                to=LINE_TARGET_ID,
                messages=[TextMessage(text=text)],
            )
        )
    logger.info(f"已發送 LINE 訊息：{text}")


def is_valid_weverse_url(url: str) -> bool:
    """簡單驗證是否為 Weverse Shop 商品頁面網址"""
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme in ("http", "https")
            and "weverse.io" in parsed.netloc
            and "/sales/" in parsed.path
        )
    except Exception:
        return False


# =====================
# 情境一：啟動時立即檢查所有追蹤商品
# 若狀態為 SALE，立即發送通知（不論之前狀態）
# =====================

def check_scenario_one(url: str) -> None:
    """
    情境一測試用：
    直接檢查商品狀態，若為 SALE 就發通知（不管先前是什麼狀態）
    """
    logger.info(f"[情境一] 立即檢查：{url}")
    info = fetch_product_info(url)
    if info is None:
        send_line_message(f"⚠️ 無法取得商品資訊，請確認網址是否正確：\n{url}")
        return

    name = info["name"]
    status = info["status"]

    # 記錄到追蹤清單（初始狀態）
    tracked_items[url] = {"name": name, "status": status}
    logger.info(f"[情境一] 商品：{name}，狀態：{status}")

    if status == "SALE":
        msg = (
            f"🛒 商品現在可以購買！\n\n"
            f"📦 商品：{name}\n"
            f"🔗 連結：{url}"
        )
        send_line_message(msg)
    else:
        status_map = {
            "SOLD_OUT": "已售完",
            "SALE_END": "銷售結束",
            "TO_BE_SOLD": "即將開賣",
            "READY_IN_STOCK": "補貨中",
        }
        readable = status_map.get(status, status)
        msg = (
            f"📋 商品目前狀態：{readable}\n\n"
            f"📦 商品：{name}\n"
            f"🔗 連結：{url}\n\n"
            f"✅ 已加入追蹤清單，每3分鐘自動檢查一次。"
        )
        send_line_message(msg)


# =====================
# 情境二：定期排程檢查（SOLD_OUT → SALE 才通知）
# =====================

def check_all_tracked_items() -> None:
    """
    排程任務（每3分鐘執行一次）：
    只在狀態從非 SALE 變成 SALE 時才發送通知。
    """
    if not tracked_items:
        logger.info("目前沒有追蹤中的商品。")
        return

    for url, prev in list(tracked_items.items()):
        info = fetch_product_info(url)
        if info is None:
            logger.warning(f"排程檢查失敗，略過：{url}")
            continue

        new_status = info["status"]
        old_status = prev["status"]
        name = info["name"]

        logger.info(f"排程檢查 [{name}]：{old_status} → {new_status}")

        # 只在狀態「從非SALE 變成 SALE」時才通知（情境二）
        if old_status != "SALE" and new_status == "SALE":
            msg = (
                f"🔔 補貨通知！商品現在可以購買！\n\n"
                f"📦 商品：{name}\n"
                f"🔗 連結：{url}"
            )
            send_line_message(msg)

        # 更新記錄狀態
        tracked_items[url]["status"] = new_status
        tracked_items[url]["name"] = name


# =====================
# LINE Webhook
# =====================

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    logger.info(f"收到 Webhook：{body}")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    user_text = event.message.text.strip()
    reply_token = event.reply_token

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # 使用者傳入網址
        if user_text.startswith("http"):
            if not is_valid_weverse_url(user_text):
                reply = "⚠️ 請傳入有效的 Weverse Shop 商品網址\n範例：https://shop.weverse.io/..."
            elif user_text in tracked_items:
                name = tracked_items[user_text]["name"]
                status = tracked_items[user_text]["status"]
                reply = f"📋 此商品已在追蹤清單中\n商品：{name}\n目前狀態：{status}"
            else:
                # 加入追蹤並執行情境一立即檢查
                reply = f"✅ 已收到網址，正在檢查商品狀態...\n{user_text}"
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[TextMessage(text=reply)],
                    )
                )
                # 執行情境一（非同步後處理，直接呼叫）
                check_scenario_one(user_text)
                return

        elif user_text in ("列表", "list", "清單"):
            if not tracked_items:
                reply = "📋 目前追蹤清單為空。"
            else:
                lines = ["📋 追蹤中的商品：\n"]
                status_map = {
                    "SALE": "✅ 可購買",
                    "SOLD_OUT": "❌ 售完",
                    "SALE_END": "🚫 銷售結束",
                    "TO_BE_SOLD": "⏳ 即將開賣",
                    "READY_IN_STOCK": "🔄 補貨中",
                }
                for i, (u, v) in enumerate(tracked_items.items(), 1):
                    s = status_map.get(v["status"], v["status"])
                    lines.append(f"{i}. {v['name']}\n   {s}\n   {u}")
                reply = "\n".join(lines)

        elif user_text in ("說明", "help", "指令"):
            reply = (
                "📖 使用說明：\n\n"
                "1️⃣ 傳入 Weverse Shop 商品網址\n"
                "   → 立即檢查狀態並加入追蹤\n\n"
                "2️⃣ 傳「列表」或「list」\n"
                "   → 查看所有追蹤中的商品\n\n"
                "3️⃣ 補貨通知\n"
                "   → 商品從售完變為可購買時自動通知"
            )
        else:
            reply = "傳入 Weverse Shop 商品網址即可開始追蹤 🛍️\n\n輸入「說明」查看使用方式。"

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=reply)],
            )
        )


# =====================
# 主程式
# =====================

if __name__ == "__main__":
    # 啟動排程器（每3分鐘檢查一次）
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        check_all_tracked_items,
        trigger="interval",
        minutes=3,
        id="monitor_job",
    )
    scheduler.start()
    logger.info("排程器已啟動，每3分鐘檢查一次追蹤商品。")

    # 啟動 Flask
    app.run(host="0.0.0.0", port=5000, debug=False)
