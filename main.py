import os
import io
import json
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from google.cloud import vision
from google.oauth2 import service_account
from googleapiclient.discovery import build
from PIL import Image

app = FastAPI()

# ===== ENV =====
LINE_TOKEN = os.getenv("LINE_TOKEN")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS")

assert LINE_TOKEN, "Missing LINE_TOKEN"
assert GOOGLE_CREDENTIALS_JSON, "Missing GOOGLE_CREDENTIALS"

creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=[
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets",
    ],
)

vision_client = vision.ImageAnnotatorClient(credentials=credentials)
sheets_service = build("sheets", "v4", credentials=credentials)
drive_service = build("drive", "v3", credentials=credentials)

# ===== UTIL =====

def reply(token, text):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}",
    }
    payload = {
        "replyToken": token,
        "messages": [{"type": "text", "text": text}],
    }
    requests.post(url, headers=headers, json=payload)

def get_image_content(message_id):
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    res = requests.get(url, headers=headers)
    res.raise_for_status()
    return res.content

def ocr_image(image_bytes):
    image = vision.Image(content=image_bytes)
    response = vision_client.text_detection(image=image)
    texts = response.text_annotations
    if not texts:
        return ""
    return texts[0].description

def extract_amount(text):
    # ดึงตัวเลขที่ดูเหมือนยอดรวม
    import re
    candidates = re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d{2})?", text.replace(" ", ""))
    if not candidates:
        return None
    # เอาค่ามากสุดเป็นยอดรวมโดยประมาณ
    def to_float(x): return float(x.replace(",", ""))
    return max(candidates, key=to_float)

def classify(text):
    t = text.lower()
    if any(k in t for k in ["grab", "lineman", "food", "restaurant", "cafe", "กาแฟ", "อาหาร"]):
        return "ค่าอาหาร"
    if any(k in t for k in ["taxi", "grabcar", "bolt", "รถ", "ทางด่วน", "น้ำมัน"]):
        return "ค่าเดินทาง"
    if any(k in t for k in ["material", "วัตถุดิบ", "ของสด", "ตลาด"]):
        return "ค่าวัตถุดิบ"
    if any(k in t for k in ["equipment", "อุปกรณ์"]):
        return "ค่าอุปกรณ์"
    return "ค่าใช้จ่ายทั่วไป"

def get_or_create_sheet(group_id, group_name):
    # ค้นหาไฟล์ตาม group_id
    query = f"name contains '{group_id}' and mimeType='application/vnd.google-apps.spreadsheet'"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"], files[0]["name"]

    # สร้างไฟล์ใหม่
    title = f"BILIX-{group_name}-{group_id}"
    spreadsheet = sheets_service.spreadsheets().create(
        body={"properties": {"title": title}}
    ).execute()
    sheet_id = spreadsheet["spreadsheetId"]

    # ใส่ header
    values = [["วันที่", "ร้าน", "หมวด", "ยอดเงิน", "ผู้ส่ง", "หมายเหตุ"]]
    sheets_service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range="Sheet1!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    return sheet_id, title

def append_row(sheet_id, row):
    sheets_service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range="Sheet1!A1",
        valueInputOption="RAW",
        body={"values": [row]},
    ).execute()

def get_total(sheet_id):
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=sheet_id, range="Sheet1!D:D"
    ).execute()
    values = result.get("values", [])
    total = 0.0
    for v in values[1:]:
        try:
            total += float(v[0].replace(",", ""))
        except:
            pass
    return total

# ===== WEBHOOK =====

@app.post("/webhook")
async def webhook(req: Request):
    body = await req.json()
    events = body.get("events", [])

    for event in events:
        reply_token = event.get("replyToken")
        source = event.get("source", {})
        group_id = source.get("groupId", "private")
        user_id = source.get("userId", "")
        group_name = source.get("groupId", "PrivateChat")

        message = event.get("message", {})
        mtype = message.get("type")

        # ข้อความ
        import re

def parse_text_bill(text):
    pattern = r"(.+?)\s+(\d+)"
    match = re.match(pattern, text.strip())
    if match:
        category = match.group(1)
        amount = int(match.group(2))
        return category, amount
    return None, None


# ใน handler เดิมของคุณ
if event.message.type == "text":
    user_text = event.message.text.strip()

    category, amount = parse_text_bill(user_text)

    if amount:
        # ตรงนี้ให้เรียกฟังก์ชันบันทึกลง Google Sheet ตัวเดิมที่คุณใช้กับบิล
        save_to_sheet(group_id, category, amount)

        total = get_group_total(group_id)

        reply_text = f"""🧾 ใบสรุปค่าใช้จ่าย
หมวด: {category}
ยอด: {amount:,} บาท

รวมสะสม: {total:,} บาท
"""
        reply(reply_text)

    else:
        reply("🧾 BILIX พร้อมบันทึกบิลแล้วครับ\nส่งรูปบิล หรือพิมพ์ยอดเช่น: อาหาร 320")
            continue

        # รูปภาพ (บิล)
        if mtype == "image":
            try:
                image_bytes = get_image_content(message["id"])
                text = ocr_image(image_bytes)

                amount = extract_amount(text)
                category = classify(text)

                sheet_id, sheet_name = get_or_create_sheet(group_id, group_name)

                from datetime import datetime
                date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

                row = [
                    date_str,
                    "จากรูปบิล",
                    category,
                    amount or "",
                    user_id,
                    text[:200],
                ]
                append_row(sheet_id, row)

                total = get_total(sheet_id)

                reply(
                    reply_token,
                    f"✅ บันทึกบิลสำเร็จ\n"
                    f"หมวด: {category}\n"
                    f"ยอด: {amount or 'ไม่พบ'} บาท\n\n"
                    f"📊 ยอดรวมสะสม: {total:.2f} บาท"
                )

            except Exception as e:
                reply(reply_token, f"❌ เกิดข้อผิดพลาดในการอ่านบิล\n{e}")

    return PlainTextResponse("OK")
