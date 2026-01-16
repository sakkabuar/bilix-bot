import os
import json
import re
import requests
from fastapi import FastAPI, Request
from google.cloud import vision
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = FastAPI()

# ---------------- CONFIG ----------------

LINE_TOKEN = os.getenv("LINE_TOKEN")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")

# Google Vision Client
credentials_info = json.loads(GOOGLE_CREDENTIALS)
credentials = service_account.Credentials.from_service_account_info(credentials_info)
vision_client = vision.ImageAnnotatorClient(credentials=credentials)

# Google Sheet API
sheets_service = build("sheets", "v4", credentials=credentials)

SPREADSHEET_ID = credentials_info["SPREADSHEET_ID"]

# ---------------- HELPERS ----------------

def reply(reply_token, message):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": message}]
    }
    requests.post(url, headers=headers, json=data)

def parse_text_bill(text):
    match = re.match(r"(.+?)\s+(\d+)", text.strip())
    if match:
        return match.group(1), int(match.group(2))
    return None, None

def detect_text_from_image(image_content):
    image = vision.Image(content=image_content)
    response = vision_client.text_detection(image=image)
    texts = response.text_annotations
    if texts:
        return texts[0].description
    return ""

def extract_amount(text):
    numbers = re.findall(r"\d+", text.replace(",", ""))
    if numbers:
        return max([int(n) for n in numbers])
    return None

# ---------------- GOOGLE SHEET ----------------

def get_sheet_name(group_id):
    return f"group_{group_id[-6:]}"

def ensure_sheet(sheet_name):
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheets = spreadsheet.get("sheets", [])

    for s in sheets:
        if s["properties"]["title"] == sheet_name:
            return

    body = {
        "requests": [{
            "addSheet": {
                "properties": {"title": sheet_name}
            }
        }]
    }
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body=body
    ).execute()

def append_row(sheet_name, category, amount):
    values = [[category, amount]]
    body = {"values": values}

    sheets_service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{sheet_name}!A:B",
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()

def get_total(sheet_name):
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{sheet_name}!B:B"
    ).execute()

    values = result.get("values", [])
    total = sum(int(v[0]) for v in values if v and v[0].isdigit())
    return total

# ---------------- LINE WEBHOOK ----------------

@app.post("/webhook")
async def webhook(req: Request):
    body = await req.json()
    events = body.get("events", [])

    for event in events:
        reply_token = event["replyToken"]
        group_id = event["source"].get("groupId", "private")
        sheet_name = get_sheet_name(group_id)
        ensure_sheet(sheet_name)

        msg = event["message"]

        # ---------- TEXT MODE ----------
        if msg["type"] == "text":
            text = msg["text"]
            category, amount = parse_text_bill(text)

            if amount:
                append_row(sheet_name, category, amount)
                total = get_total(sheet_name)

                reply_text = f"""🧾 ใบสรุปค่าใช้จ่าย
หมวด: {category}
ยอด: {amount:,} บาท

รวมสะสม: {total:,} บาท
"""
                reply(reply_token, reply_text)
            else:
                reply(reply_token, "🧾 BILIX พร้อมบันทึกบิลแล้วครับ\nส่งรูปบิล หรือพิมพ์เช่น: อาหาร 320")

        # ---------- IMAGE MODE ----------
        elif msg["type"] == "image":
            message_id = msg["id"]
            headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
            img_url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
            img_res = requests.get(img_url, headers=headers)

            text = detect_text_from_image(img_res.content)
            amount = extract_amount(text)

            if amount:
                category = "บิล"
                append_row(sheet_name, category, amount)
                total = get_total(sheet_name)

                reply_text = f"""🧾 ใบสรุปจากบิล
ยอด: {amount:,} บาท

รวมสะสม: {total:,} บาท
"""
                reply(reply_token, reply_text)
            else:
                reply(reply_token, "❌ อ่านบิลไม่สำเร็จ กรุณาลองถ่ายใหม่ให้ชัดขึ้นครับ")

    return {"status": "ok"}
