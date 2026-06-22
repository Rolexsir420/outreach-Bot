import csv
import io
import os
import random
import asyncio
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import pytz
from pyrogram import Client
from pyrogram.errors import FloodWait, UserPrivacyRestricted, PeerIdInvalid, UserIsBlocked, InviteHashInvalid, InviteHashExpired

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

IST = pytz.timezone("Asia/Kolkata")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_1")
LOG_CHANNEL = int(os.getenv("LOG_CHANNEL"))
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", 25))

loop = asyncio.new_event_loop()
telegram_client = Client(
    "outreach",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)
MY_ID = None
processing = False
processing_lock = threading.Lock()

def run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

async def init_bot():
    global MY_ID
    await telegram_client.start()
    me = await telegram_client.get_me()
    MY_ID = me.id
    async for _ in telegram_client.get_dialogs():
        pass
    await telegram_client.send_message(LOG_CHANNEL,
        f"✅ **Outreach Web Bot Online**\n"
        f"👤 Account : {me.first_name}\n"
        f"📨 Daily limit : {DAILY_LIMIT}\n"
        f"🕐 Time : {datetime.now(IST).strftime('%d %b %Y, %H:%M IST')}"
    )
    print(f"Bot startup complete. MY_ID={MY_ID}")

def read_csv(file):
    contacts = []
    stream = io.StringIO(file.read().decode('utf-8'))
    reader = csv.DictReader(stream)
    for row in reader:
        contacts.append({
            "uid": int(row.get("uid", 0)),
            "username": row.get("username", "N/A"),
            "name": row.get("name", "Unknown"),
        })
    return contacts

async def send_to_user(contact, msg_text, serial):
    uid = contact["uid"]
    name = contact["name"]
    profile_link = f"tg://user?id={uid}"
    try:
        personalised = msg_text.replace("{name}", name.split()[0] if name else "there")
        await telegram_client.send_message(uid, personalised)
        await telegram_client.send_message(LOG_CHANNEL,
            f"✅ **#{serial} SENT**\n👤 [{name}]({profile_link})\n🕐 {datetime.now(IST).strftime('%H:%M IST')}",
            disable_web_page_preview=True
        )
        return "sent"
    except UserPrivacyRestricted:
        await telegram_client.send_message(LOG_CHANNEL,
            f"⚠️ **#{serial} SKIPPED**\n👤 [{name}]({profile_link})\n❌ Privacy restricted",
            disable_web_page_preview=True
        )
        return "skipped"
    except (UserIsBlocked, PeerIdInvalid) as e:
        await telegram_client.send_message(LOG_CHANNEL,
            f"⚠️ **#{serial} SKIPPED**\n👤 [{name}]({profile_link})\n❌ {type(e).__name__}",
            disable_web_page_preview=True
        )
        return "skipped"
    except FloodWait as fw:
        await asyncio.sleep(fw.value + 5)
        return await send_to_user(contact, msg_text, serial)
    except Exception as e:
        print(f"Error sending to {uid}: {e}")
        return "failed"

async def run_outreach(contacts, message, group_link):
    global processing
    total_sent = total_skipped = total_failed = 0
    now = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    
    try:
        await telegram_client.send_message(LOG_CHANNEL,
            f"📤 **OUTREACH STARTED**\n📋 Total : {len(contacts)}\n🕐 {now}"
        )
        
        # Step 1: Join group
        try:
            await telegram_client.send_message(LOG_CHANNEL, f"🔗 Joining group...")
            await telegram_client.join_chat(group_link)
            await telegram_client.send_message(LOG_CHANNEL, f"✅ Successfully joined group")
            print("✅ Bot joined group")
        except InviteHashInvalid:
            await telegram_client.send_message(LOG_CHANNEL, f"❌ Invalid group link")
            processing = False
            return
        except InviteHashExpired:
            await telegram_client.send_message(LOG_CHANNEL, f"❌ Group invite link expired")
            processing = False
            return
        except Exception as e:
            await telegram_client.send_message(LOG_CHANNEL, f"❌ Failed to join group: {type(e).__name__}")
            print(f"Error joining group: {e}")
            processing = False
            return
        
        # Step 2: Load all members into peer cache
        try:
            await telegram_client.send_message(LOG_CHANNEL, f"📥 Loading peer cache...")
            member_count = 0
            async for member in telegram_client.get_chat_members(group_link):
                member_count += 1
            await telegram_client.send_message(LOG_CHANNEL, f"✅ Loaded {member_count} members into cache")
            print(f"✅ Loaded {member_count} members into peer cache")
        except Exception as e:
            await telegram_client.send_message(LOG_CHANNEL, f"⚠️ Error loading peers: {type(e).__name__}")
            print(f"Error loading peers: {e}")
        
        # Step 3: Leave group
        try:
            await telegram_client.send_message(LOG_CHANNEL, f"👋 Leaving group...")
            await telegram_client.leave_chat(group_link)
            await telegram_client.send_message(LOG_CHANNEL, f"✅ Left group successfully")
            print("✅ Bot left group")
        except Exception as e:
            await telegram_client.send_message(LOG_CHANNEL, f"⚠️ Error leaving group: {type(e).__name__}")
            print(f"Error leaving group: {e}")
        
        # Step 4: Send DMs (all UIDs are now valid peers)
        await telegram_client.send_message(LOG_CHANNEL, f"💬 Starting to send DMs...")
        
        for serial, contact in enumerate(contacts, start=1):
            try:
                result = await send_to_user(contact, message, serial)
            except Exception as e:
                print(f"Unhandled error on #{serial}: {e}")
                try:
                    await telegram_client.send_message(LOG_CHANNEL,
                        f"❌ **#{serial} ERROR**\n{type(e).__name__}: {str(e)[:50]}"
                    )
                except Exception:
                    pass
                result = "failed"
            
            if result == "sent": total_sent += 1
            elif result == "skipped": total_skipped += 1
            else: total_failed += 1
            
            delay = random.randint(45, 90)
            print(f"Waiting {delay}s...")
            await asyncio.sleep(delay)
        
        end_time = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
        await telegram_client.send_message(LOG_CHANNEL,
            f"✅ **OUTREACH COMPLETE**\n📨 Sent : {total_sent}\n⚠️ Skipped : {total_skipped}\n❌ Failed : {total_failed}\n🕐 {end_time}"
        )
    
    except Exception as e:
        print(f"run_outreach crashed: {e}")
        try:
            await telegram_client.send_message(LOG_CHANNEL,
                f"🛑 **OUTREACH CRASHED**\n{type(e).__name__}\n"
                f"📨 Sent so far : {total_sent}\n⚠️ Skipped : {total_skipped}\n❌ Failed : {total_failed}"
            )
        except Exception:
            pass
    
    finally:
        with processing_lock:
            processing = False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/send', methods=['POST'])
def send():
    global processing
    with processing_lock:
        if processing:
            return jsonify({"error": "Already processing. Please wait."}), 400
        processing = True
    
    if 'csv_file' not in request.files:
        with processing_lock:
            processing = False
        return jsonify({"error": "No CSV file provided"}), 400
    
    message = request.form.get('message', '').strip()
    if not message:
        with processing_lock:
            processing = False
        return jsonify({"error": "No message provided"}), 400
    
    group_link = request.form.get('group_link', '').strip()
    if not group_link:
        with processing_lock:
            processing = False
        return jsonify({"error": "No group link provided"}), 400
    
    csv_file = request.files['csv_file']
    if not csv_file.filename.endswith('.csv'):
        with processing_lock:
            processing = False
        return jsonify({"error": "Please upload a CSV file"}), 400
    
    contacts = read_csv(csv_file)
    if not contacts:
        with processing_lock:
            processing = False
        return jsonify({"error": "CSV is empty or invalid"}), 400
    
    limited = contacts[:DAILY_LIMIT]
    
    # Fire and forget — don't wait for it to finish
    asyncio.run_coroutine_threadsafe(run_outreach(limited, message, group_link), loop)
    
    return jsonify({
        "success": True,
        "sent": len(limited),
        "skipped": 0,
        "failed": 0,
        "note": "Job started! Bot will join group, load peers, leave, then send DMs. Check log channel for live updates."
    })

if __name__ == '__main__':
    t = threading.Thread(target=run_loop, args=(loop,), daemon=True)
    t.start()
    asyncio.run_coroutine_threadsafe(init_bot(), loop).result(timeout=60)
    app.run(host='0.0.0.0', port=5000, debug=False)
