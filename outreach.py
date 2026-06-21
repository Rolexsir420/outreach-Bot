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
LOG_CHANNEL = int(os.getenv("LOG_CHANNEL"))
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", 25))
INVITE_LINK = os.getenv("INVITE_LINK", "")

SESSION_STRINGS = []
for i in range(1, 6):
    s = os.getenv(f"SESSION_{i}")
    if s:
        SESSION_STRINGS.append(s)

# ── create clients for each account ──────────────────────────────────
clients = []
for idx, session in enumerate(SESSION_STRINGS):
    clients.append(Client(
        f"account_{idx+1}",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=session
    ))

PRIMARY_CLIENT = clients[0]
MY_ID = None

# ── startup ───────────────────────────────────────────────────────────
async def on_start():
    global MY_ID
    try:
        me = await PRIMARY_CLIENT.get_me()
        MY_ID = me.id

        async for dialog in PRIMARY_CLIENT.get_dialogs():
            pass

        await PRIMARY_CLIENT.get_chat(LOG_CHANNEL)

        account_names = []
        for c in clients:
            u = await c.get_me()
            account_names.append(u.first_name)

        await PRIMARY_CLIENT.send_message(LOG_CHANNEL,
            f"✅ **Outreach Bot Online**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Accounts ready : {len(clients)}\n"
            f"📋 Accounts       : {', '.join(account_names)}\n"
            f"📨 Daily limit    : {DAILY_LIMIT} per account\n"
            f"🕐 Time           : {datetime.now(IST).strftime('%d %b %Y, %H:%M IST')}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
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
                    "profile_link": row.get("profile_link",
                        f"tg://user?id={row.get('uid', 0)}")
                })
        os.remove(file_path)
    except Exception as e:
        print(f"CSV read error: {e}")
    return contacts

# ── send message to one user ──────────────────────────────────────────
async def send_to_user(client: Client, contact: dict, msg_text: str, serial: int, account_name: str):
    uid = contact["uid"]
    name = contact["name"]
    profile_link = f"tg://user?id={uid}"

    try:
        # personalise message
        personalised = msg_text.replace("{name}", name.split()[0] if name else "there")

        await client.send_message(uid, personalised)

        await PRIMARY_CLIENT.send_message(LOG_CHANNEL,
            f"✅ **#{serial} SENT**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 [{name}]({profile_link})\n"
            f"📤 Via : {account_name}\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            disable_web_page_preview=True
        )
        return "sent"

    except UserPrivacyRestricted:
        await PRIMARY_CLIENT.send_message(LOG_CHANNEL,
            f"⚠️ **#{serial} SKIPPED**\n"
            f"👤 [{name}]({profile_link})\n"
            f"❌ Privacy restricted",
            disable_web_page_preview=True
        )
        return "skipped"

    except UserIsBlocked:
        await PRIMARY_CLIENT.send_message(LOG_CHANNEL,
            f"⚠️ **#{serial} SKIPPED**\n"
            f"👤 [{name}]({profile_link})\n"
            f"❌ User blocked this account",
            disable_web_page_preview=True
        )
        return "skipped"

    except PeerIdInvalid:
        await PRIMARY_CLIENT.send_message(LOG_CHANNEL,
            f"⚠️ **#{serial} SKIPPED**\n"
            f"👤 [{name}]({profile_link})\n"
            f"❌ Cannot reach user",
            disable_web_page_preview=True
        )
        return "skipped"

    except FloodWait as fw:
        print(f"FloodWait {fw.value}s on {account_name}")
        await asyncio.sleep(fw.value + 5)
        return await send_to_user(client, contact, msg_text, serial, account_name)

    except Exception as e:
        print(f"Error sending to {uid}: {e}")
        await PRIMARY_CLIENT.send_message(LOG_CHANNEL,
            f"❌ **#{serial} FAILED**\n"
            f"👤 [{name}]({profile_link})\n"
            f"Error: {e}",
            disable_web_page_preview=True
        )
        return "failed"

# ── send batch for one account ────────────────────────────────────────
async def send_batch(client: Client, contacts: list, msg_text: str, start_serial: int):
    me = await client.get_me()
    account_name = me.first_name
    results = {"sent": 0, "skipped": 0, "failed": 0}

    for i, contact in enumerate(contacts):
        serial = start_serial + i
        result = await send_to_user(client, contact, msg_text, serial, account_name)
        results[result] += 1

        # random delay between 45-90 seconds — looks human
        delay = random.randint(45, 90)
        print(f"{account_name} waiting {delay}s before next message...")
        await asyncio.sleep(delay)

    return results

# ── .outreach command ─────────────────────────────────────────────────
@PRIMARY_CLIENT.on_message(filters.command("outreach", prefixes=".") & filters.outgoing)
async def handle_outreach(client: Client, message: Message):
    print("Outreach command received")

    # find CSV in recent saved messages
    csv_message = None
    msg_text = None

    async for msg in client.get_chat_history("me", limit=10):
        if msg.document and msg.document.file_name.endswith(".csv"):
            csv_message = msg
            break

    if not csv_message:
        await message.reply("❌ No CSV file found in Saved Messages. Upload CSV first then type .outreach")
        return

    # find message text just above .outreach command
    async for msg in client.get_chat_history("me", limit=10):
        if msg.text and not msg.text.startswith(".outreach") and not msg.document:
            msg_text = msg.text
            break

    if not msg_text:
        await message.reply("❌ No message text found. Type your message in Saved Messages then .outreach")
        return

    # read contacts from CSV
    contacts = await read_csv_from_message(csv_message)

    if not contacts:
        await message.reply("❌ CSV is empty or invalid format")
        return

    # apply daily limit per account
    limited_contacts = contacts[:DAILY_LIMIT * len(clients)]

    # split contacts across accounts
    chunks = []
    chunk_size = DAILY_LIMIT
    for i in range(0, len(limited_contacts), chunk_size):
        chunks.append(limited_contacts[i:i + chunk_size])

    now = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    await PRIMARY_CLIENT.send_message(LOG_CHANNEL,
        f"📤 **OUTREACH STARTED**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Total contacts  : {len(limited_contacts)}\n"
        f"👥 Accounts active : {len(clients)}\n"
        f"📨 Per account     : {DAILY_LIMIT}\n"
        f"🕐 Time            : {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    # run all accounts simultaneously
    tasks = []
    serial_start = 1
    for idx, (c, chunk) in enumerate(zip(clients, chunks)):
        if chunk:
            tasks.append(send_batch(c, chunk, msg_text, serial_start))
            serial_start += len(chunk)

    all_results = await asyncio.gather(*tasks)

    # combine results
    total_sent = sum(r["sent"] for r in all_results)
    total_skipped = sum(r["skipped"] for r in all_results)
    total_failed = sum(r["failed"] for r in all_results)

    end_time = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    await PRIMARY_CLIENT.send_message(LOG_CHANNEL,
        f"✅ **OUTREACH COMPLETE**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📨 Total sent    : {total_sent}\n"
        f"⚠️ Skipped       : {total_skipped}\n"
        f"❌ Failed        : {total_failed}\n"
        f"🕐 Time          : {end_time}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

# ── entry point ───────────────────────────────────────────────────────
async def main():
    # start all clients
    for c in clients:
        await c.start()

    await on_start()
    print("Outreach bot running...")

    await asyncio.Future()

asyncio.run(main())
