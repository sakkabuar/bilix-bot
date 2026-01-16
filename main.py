from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

LINE_TOKEN = os.getenv("LINE_TOKEN")

@app.post("/webhook")
async def webhook(req: Request):
    body = await req.json()
    events = body.get("events", [])

    for event in events:
        if event["type"] == "message":
            reply_token = event["replyToken"]

            text = (
                "🧾 BILIX พร้อมบันทึกบิลแล้วครับ\n"
                "ส่งรูปบิลเข้ามาได้เลย"
            )

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LINE_TOKEN}"
            }

            data = {
                "replyToken": reply_token,
                "messages": [
                    {"type": "text", "text": text}
                ]
            }

            requests.post(
                "https://api.line.me/v2/bot/message/reply",
                headers=headers,
                json=data
            )

    return {"status": "ok"}
