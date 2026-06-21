import asyncio
import csv
import io
import os
import random
from datetime import datetime

import pytz
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, UserPrivacyRestricted, PeerIdInvalid, UserIsBlocked
from pyrogram.types import Message

load_dotenv()

IST = pytz.timezone("Asia/Kolkata")

# ── env variables ─────────────────────────────────────────────────────
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_1")
LOG_CHANNEL = int(os.getenv("LOG_CHANNEL"))
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", 25))

client = Client(
    "outreach",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

MY_ID = None
processing = False

# ── startup ───────────────────────────────────────────────────────────
async def on_start():
    global MY_ID
    try:
        me = await client.get_me()
        MY_ID = me.id

        async for dialog in client.get_dialogs():
            pass

        await client.get_chat(LOG_CHANNEL)

        await client.send_message(LOG_CHANNEL,
            f"✅ **Outreach Bot Online**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Account : {me.first_name}\n"
            f"📨 Daily limit : {DAILY_LIMIT}\n"
            f"🕐 Time : {datetime.now(IST).strftime('%d %b %Y, %H:%M IST')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 Upload CSV to Saved Messages\n"
            f"📝 Type your message above CSV\n"
            f"⏳ Bot auto-detects and sends"
        )
        print(f"Startup complete. MY_ID={MY_ID}")
    except Exception as e:
        print(f"Startup error: {e}")

# ── read csv from message ─────────────────────────────────────────────
async def read_csv_from_message(message: Message) -> list:
    contacts = []
    try:
        file_path = await message.download()
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                contacts.append({
                    "uid": int(row.get("uid", 0)),
                    "username": row.get("username", "N/A"),
                    "name": row.get("name", "Unknown"),
                })
        os.remove(file_path)
    except Exception as e:
        print(f"CSV read error: {e}")
    return contacts

# ── send message to one user ──────────────────────────────────────────
async def send_to_user(contact: dict, msg_text: str, serial: int):
    uid = contact["uid"]
    name = contact["name"]
    profile_link = f"tg://user?id={uid}"

    try:
        personalised = msg_text.replace("{name}", name.split()[0] if name else "there")
        await client.send_message(uid, personalised)

        await client.send_message(LOG_CHANNEL,
            f"✅ **#{serial} SENT**\n"
            f"👤 [{name}]({profile_link})\n"
            f"🕐 {datetime.now(IST).strftime('%H:%M IST')}",
            disable_web_page_preview=True
        )
        return "sent"

    except UserPrivacyRestricted:
        await client.send_message(LOG_CHANNEL,
            f"⚠️ **#{serial} SKIPPED**\n"
            f"👤 [{name}]({profile_link})\n"
            f"❌ Privacy restricted",
            disable_web_page_preview=True
        )
        return "skipped"

    except UserIsBlocked:
        return "skipped"

    except PeerIdInvalid:
        return "skipped"

    except FloodWait as fw:
        print(f"FloodWait {fw.value}s")
        await asyncio.sleep(fw.value + 5)
        return await send_to_user(contact, msg_text, serial)

    except Exception as e:
        print(f"Error sending to {uid}: {e}")
        return "failed"

# ── auto detect CSV and send ──────────────────────────────────────────
@client.on_message(filters.document & filters.outgoing)
async def handle_csv(client: Client, message: Message):
    global processing
    
    if processing:
        return
    
    # Check if it's a CSV file
    if not message.document.file_name.endswith(".csv"):
        return

    processing = True
    print("CSV detected! Starting outreach...")

    try:
        # Find message text just above CSV
        msg_text = None
        async for msg in client.get_chat_history("me", limit=5):
            if msg.text and not msg.document and msg.id < message.id:
                msg_text = msg.text
                break

        if not msg_text:
            await client.send_message(LOG_CHANNEL,
                "❌ No message text found above CSV. Type your message first, then upload CSV.")
            processing = False
            return

        # Read contacts from CSV
        contacts = await read_csv_from_message(message)

        if not contacts:
            await client.send_message(LOG_CHANNEL,
                "❌ CSV is empty or invalid format")
            processing = False
            return

        # Apply daily limit
        limited_contacts = contacts[:DAILY_LIMIT]

        now = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
        await client.send_message(LOG_CHANNEL,
            f"📤 **OUTREACH STARTED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 Total contacts : {len(limited_contacts)}\n"
            f"🕐 Time : {now}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

        # Send to all contacts
        total_sent = 0
        total_skipped = 0
        total_failed = 0

        for serial, contact in enumerate(limited_contacts, start=1):
            result = await send_to_user(contact, msg_text, serial)
            
            if result == "sent":
                total_sent += 1
            elif result == "skipped":
                total_skipped += 1
            else:
                total_failed += 1

            # Random delay 45-90 seconds
            delay = random.randint(45, 90)
            print(f"Waiting {delay}s before next message...")
            await asyncio.sleep(delay)

        end_time = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
        await client.send_message(LOG_CHANNEL,
            f"✅ **OUTREACH COMPLETE**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📨 Total sent : {total_sent}\n"
            f"⚠️ Skipped : {total_skipped}\n"
            f"❌ Failed : {total_failed}\n"
            f"🕐 Time : {end_time}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

    finally:
        processing = False

# ── entry point ───────────────────────────────────────────────────────
async def main():
    await client.start()
    await on_start()
    print("Outreach bot running...")
    await asyncio.Event().wait()

asyncio.run(main())
