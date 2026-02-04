import os
import json
from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)
import firebase_admin
from firebase_admin import credentials, db

# ================= LOAD ENV =================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
BOT_USERNAME = os.getenv("BOT_USERNAME")
DB_URL = os.getenv("FIREBASE_DB_URL")
PAYMENT_LINK = os.getenv("PAYSTACK_PAYMENT_LINK")
DRIVE_LINK = os.getenv("DRIVE_LINK")

# ================= FIREBASE INIT =================
firebase_json = os.getenv("FIREBASE_KEY_JSON")
cred_dict = json.loads(firebase_json)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred, {"databaseURL": DB_URL})

users_ref = db.reference("users")

# ================= HELPERS =================
def get_or_create_user(uid, referrer=None):
    user = users_ref.child(str(uid)).get()
    if not user:
        users_ref.child(str(uid)).set({
            "approved": False,
            "paid_link_opened": False,
            "email_sent": False,
            "balance": 0,
            "referrals": 0,
            "referred_by": referrer
        })
        user = users_ref.child(str(uid)).get()
    return user

def main_keyboard(approved):
    if not approved:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Pay Registration (KES 300)", callback_data="pay")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Library", callback_data="library")],
        [InlineKeyboardButton("👥 Referral Link", callback_data="ref")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")]
    ])

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    referrer = context.args[0] if context.args else None
    user = get_or_create_user(uid, referrer)

    await update.message.reply_text(
        "Welcome to TONalt.\n\nPlease complete registration to continue." if not user["approved"] else "✅ Access unlocked.",
        reply_markup=main_keyboard(user["approved"])
    )

# ================= CALLBACKS =================
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    user = get_or_create_user(uid)

    if q.data == "pay":
        users_ref.child(str(uid)).update({"paid_link_opened": True})
        await q.message.reply_text(
            f"Click the link below to pay:\n\n{PAYMENT_LINK}\n\n"
            "After payment, click *I've Paid*.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ I've Paid", callback_data="verify")]
            ])
        )

    elif q.data == "verify":
        if not user["paid_link_opened"]:
            await q.message.reply_text("⚠️ You must open the payment link first.")
            return
        await q.message.reply_text("Please send the **email used for payment**.")
        context.user_data["awaiting_email"] = True

    elif q.data.startswith("approve_"):
        target = q.data.split("_")[1]
        users_ref.child(target).update({"approved": True})

        # Reward referrer if exists
        referrer = users_ref.child(target).child("referred_by").get()
        if referrer:
            ref_data = users_ref.child(referrer).get()
            if ref_data:
                new_balance = ref_data.get("balance", 0) + 100
                new_referrals = ref_data.get("referrals", 0) + 1
                users_ref.child(referrer).update({
                    "balance": new_balance,
                    "referrals": new_referrals
                })

        await context.bot.send_message(
            chat_id=int(target),
            text="✅ Payment approved. Access unlocked.",
            reply_markup=main_keyboard(True)
        )
        await q.edit_message_text("User approved.")

    elif q.data.startswith("reject_"):
        target = q.data.split("_")[1]
        await context.bot.send_message(
            chat_id=int(target),
            text="❌ Payment rejected. Please contact support."
        )
        await q.edit_message_text("User rejected.")

    elif q.data.startswith("paid_"):
        target = q.data.split("_")[1]
        users_ref.child(target).update({"balance": 0})
        await context.bot.send_message(
            chat_id=int(target),
            text="✅ Your withdrawal has been paid."
        )
        await q.edit_message_text("Withdrawal marked as paid.")

    elif q.data == "library":
        await q.message.reply_text(f"📚 Access your library:\n{DRIVE_LINK}")

    elif q.data == "ref":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={uid}"
        await q.message.reply_text(f"👥 Your referral link:\n{ref_link}")

    elif q.data == "withdraw":
        if user["balance"] < 200:
            await q.message.reply_text("❌ Your balance is below the minimum withdrawal (KES 200).")
            return
        await q.message.reply_text(
            f"💰 Your balance is KES {user['balance']}.\n\nPlease send:\nName\nPhone Number"
        )
        context.user_data["awaiting_withdraw"] = True

# ================= MESSAGES =================
async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_or_create_user(uid)
    text = update.message.text

    if context.user_data.get("awaiting_email"):
        users_ref.child(str(uid)).update({
            "email_sent": True,
            "email": text
        })
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"💳 PAYMENT VERIFICATION\n\nUser ID: {uid}\nEmail: {text}",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{uid}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{uid}")
                ]
            ])
        )
        context.user_data.clear()
        await update.message.reply_text("⏳ Awaiting admin approval.")

    elif context.user_data.get("awaiting_withdraw"):
        lines = text.split("\n")
        if len(lines) < 2:
            await update.message.reply_text("Send name and phone on separate lines.")
            return

        fee = 20 * ((user["balance"] - 1) // 1000 + 1)
        payout = user["balance"] - fee

        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"💸 WITHDRAW REQUEST\n\nUser: {uid}\nName: {lines[0]}\nPhone: {lines[1]}\n"
            f"Amount: {user['balance']} | Fee: {fee} | Pay: {payout}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Paid", callback_data=f"paid_{uid}")]
            ])
        )
        context.user_data.clear()
        await update.message.reply_text("✅ Withdrawal request sent. Await admin processing.")

# ================= MAIN =================
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# ... your imports, Firebase setup, handlers etc ...

if __name__ == "__main__":
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callbacks))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages))

    print("🚀 BOT RUNNING VIA WEBHOOK")

    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        url_path=BOT_TOKEN,
        webhook_url=f"https://tonalt-bot.onrender.com/{BOT_TOKEN}"
    )


