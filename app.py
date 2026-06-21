import asyncio
import csv
import io
import os
import random
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import pytz
from pyrogram import Client
from pyrogram.errors import FloodWait, UserPrivacyRestricted, PeerIdInvalid, UserIsBlocked

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

IST = pytz.timezone("Asia/Kolkata")

# ── env variables ─────────────────────────────────────────────────────
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_1")
LOG_CHANNEL = int(os.getenv("LOG_CHANNEL"))
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", 25))

telegram_client = Client(
    "outreach",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

MY_ID = None
processing = False

# ── startup ───────────────────────────────────────────────────────────
async def init_bot():
    global MY_ID
    try:
        await telegram_client.start()
        me = await telegram_client.get_me()
        MY_ID = me.id

        async for dialog in telegram_client.get_dialogs():
            pass

        await telegram_client.get_chat(LOG_CHANNEL)

        await telegram_client.send_message(LOG_CHANNEL,
            f"✅ **Outreach Web Bot Online**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Account : {me.first_name}\n"
            f"📨 Daily limit : {DAILY_LIMIT}\n"
            f"🕐 Time : {datetime.now(IST).strftime('%d %b %Y, %H:%M IST')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Web form ready at: /\n"
            f"Upload CSV → Type message → Send"
        )
        print(f"Bot startup complete. MY_ID={MY_ID}")
    except Exception as e:
        print(f"Startup error: {e}")

# ── read csv ──────────────────────────────────────────────────────────
def read_csv(file):
    contacts = []
    try:
        stream = io.StringIO(file.read().decode('utf-8'))
        reader = csv.DictReader(stream)
        for row in reader:
            contacts.append({
                "uid": int(row.get("uid", 0)),
                "username": row.get("username", "N/A"),
                "name": row.get("name", "Unknown"),
            })
    except Exception as e:
        print(f"CSV read error: {e}")
    return contacts

# ── send to user ──────────────────────────────────────────────────────
async def send_to_user(contact, msg_text, serial):
    uid = contact["uid"]
    name = contact["name"]
    profile_link = f"tg://user?id={uid}"

    try:
        personalised = msg_text.replace("{name}", name.split()[0] if name else "there")
        await telegram_client.send_message(uid, personalised)

        await telegram_client.send_message(LOG_CHANNEL,
            f"✅ **#{serial} SENT**\n"
            f"👤 [{name}]({profile_link})\n"
            f"🕐 {datetime.now(IST).strftime('%H:%M IST')}",
            disable_web_page_preview=True
        )
        return "sent"

    except UserPrivacyRestricted:
        await telegram_client.send_message(LOG_CHANNEL,
            f"⚠️ **#{serial} SKIPPED**\n"
            f"👤 [{name}]({profile_link})\n"
            f"❌ Privacy restricted",
            disable_web_page_preview=True
        )
        return "skipped"

    except (UserIsBlocked, PeerIdInvalid):
        return "skipped"

    except FloodWait as fw:
        print(f"FloodWait {fw.value}s")
        await asyncio.sleep(fw.value + 5)
        return await send_to_user(contact, msg_text, serial)

    except Exception as e:
        print(f"Error sending to {uid}: {e}")
        return "failed"

# ── web routes ────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/send', methods=['POST'])
async def send():
    global processing
    
    if processing:
        return jsonify({"error": "Already processing. Please wait."}), 400

    processing = True

    try:
        # Check files and data
        if 'csv_file' not in request.files:
            return jsonify({"error": "No CSV file provided"}), 400

        message = request.form.get('message', '').strip()
        if not message:
            return jsonify({"error": "No message provided"}), 400

        csv_file = request.files['csv_file']
        if not csv_file.filename.endswith('.csv'):
            return jsonify({"error": "Please upload a CSV file"}), 400

        # Read CSV
        contacts = read_csv(csv_file)
        if not contacts:
            return jsonify({"error": "CSV is empty or invalid"}), 400

        # Apply limit
        limited_contacts = contacts[:DAILY_LIMIT]

        now = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
        await telegram_client.send_message(LOG_CHANNEL,
            f"📤 **OUTREACH STARTED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 Total contacts : {len(limited_contacts)}\n"
            f"🕐 Time : {now}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

        # Send to all
        total_sent = 0
        total_skipped = 0
        total_failed = 0

        for serial, contact in enumerate(limited_contacts, start=1):
            result = await send_to_user(contact, message, serial)
            
            if result == "sent":
                total_sent += 1
            elif result == "skipped":
                total_skipped += 1
            else:
                total_failed += 1

            delay = random.randint(45, 90)
            print(f"Waiting {delay}s...")
            await asyncio.sleep(delay)

        end_time = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
        await telegram_client.send_message(LOG_CHANNEL,
            f"✅ **OUTREACH COMPLETE**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📨 Sent : {total_sent}\n"
            f"⚠️ Skipped : {total_skipped}\n"
            f"❌ Failed : {total_failed}\n"
            f"🕐 Time : {end_time}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

        return jsonify({
            "success": True,
            "sent": total_sent,
            "skipped": total_skipped,
            "failed": total_failed
        })

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

    finally:
        processing = False

# ── startup ───────────────────────────────────────────────────────────
if __name__ == '__main__':
    asyncio.run(init_bot())
    app.run(host='0.0.0.0', port=5000, debug=False)
