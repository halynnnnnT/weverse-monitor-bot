# Weverse Shop 商品補貨通知 LINE Bot
一個部署在 Oracle Cloud VM 上的 Python 自動化監控工具，透過 LINE Messaging API 即時通知 Weverse Shop 商品的補貨狀態。

## 功能

- 使用者在 LINE 聊天室傳入 Weverse Shop 商品網址，Bot 自動加入追蹤清單
- 每 3 分鐘自動抓取商品頁面，解析 __NEXT_DATA__ 結構化資料取得庫存狀態
- 商品從 SOLD_OUT 變為 SALE 時，立即推播通知到 LINE 群組
- 同一商品持續 SALE 狀態不重複發送通知，避免洗版
- 支援同時追蹤多個商品網址
- 傳送「列表」可查看目前所有追蹤中的商品與狀態
