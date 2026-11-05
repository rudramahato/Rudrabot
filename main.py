import io
import logging
import os
import sqlite3
from urllib.parse import quote

import qrcode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "9278247767:AAEiI3q40uEg_3kLpzOu4doEo1UpjCGbwUM")
ADMIN_ID = int(os.getenv("ADMIN_ID", "9025357644"))  # apna Telegram numeric ID
UPI_ID = "priyamahato316@fam"
PAYEE_NAME = "Priya Mahato"
MIN_AMOUNT = 10
MAX_AMOUNT = 50000
DB_FILE = "bot.db"
# ==========================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


# ---------- Database ----------
def db():
    return sqlite3.connect(DB_FILE)


def init_db():
    with db() as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "user_id INTEGER PRIMARY KEY, name TEXT, balance REAL DEFAULT 0)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS payments ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, "
            "file_id TEXT, file_uid TEXT UNIQUE, status TEXT DEFAULT 'pending')"
        )


def ensure_user(user):
    with db() as con:
        con.execute(
            "INSERT OR IGNORE INTO users (user_id, name, balance) VALUES (?, ?, 0)",
            (user.id, user.full_name),
        )


def get_balance(user_id):
    with db() as con:
        row = con.execute(
            "SELECT balance FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
    return row[0] if row else 0.0


# ---------- Helpers ----------
def main_menu():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Add Fund", callback_data="add_fund")],
            [InlineKeyboardButton("👛 Wallet", callback_data="wallet")],
        ]
    )


def make_qr(amount: float) -> io.BytesIO:
    upi_url = (
        f"upi://pay?pa={UPI_ID}&pn={quote(PAYEE_NAME)}"
        f"&am={amount:.2f}&cu=INR&tn={quote('Add Fund')}"
    )
    img = qrcode.make(upi_url)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio


# ---------- User handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    context.user_data.clear()
    await update.message.reply_text(
        f"👋 Welcome {update.effective_user.first_name}!\n\n"
        "Neeche se option select karein:",
        reply_markup=main_menu(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = query.from_user
    ensure_user(user)

    # ----- Admin approve / reject -----
    if data.startswith(("approve_", "reject_")):
        if user.id != ADMIN_ID:
            await query.answer("❌ Sirf admin ke liye hai.", show_alert=True)
            return
        action, pid = data.split("_")
        pid = int(pid)
        with db() as con:
            row = con.execute(
                "SELECT user_id, amount, status FROM payments WHERE id=?", (pid,)
            ).fetchone()
            if not row:
                await query.answer("Payment nahi mila.", show_alert=True)
                return
            uid, amount, status = row
            if status != "pending":
                await query.answer(f"Already {status}.", show_alert=True)
                return
            if action == "approve":
                con.execute("UPDATE payments SET status='approved' WHERE id=?", (pid,))
                con.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id=?",
                    (amount, uid),
                )
            else:
                con.execute("UPDATE payments SET status='rejected' WHERE id=?", (pid,))

        if action == "approve":
            await query.edit_message_caption(
                caption=f"✅ APPROVED\nPayment #{pid} | User: {uid} | ₹{amount:.2f}"
            )
            await context.bot.send_message(
                uid,
                f"✅ Aapka ₹{amount:.2f} ka payment approve ho gaya!\n"
                f"💰 Wallet Balance: ₹{get_balance(uid):.2f}",
                reply_markup=main_menu(),
            )
        else:
            await query.edit_message_caption(
                caption=f"❌ REJECTED\nPayment #{pid} | User: {uid} | ₹{amount:.2f}"
            )
            await context.bot.send_message(
                uid,
                f"❌ Aapka ₹{amount:.2f} ka payment reject ho gaya.\n"
                "Koi problem ho to admin se contact karein.",
                reply_markup=main_menu(),
            )
        await query.answer("Done")
        return

    # ----- User buttons -----
    await query.answer()

    if data == "wallet":
        await query.message.reply_text(
            f"👛 Aapka Wallet Balance: ₹{get_balance(user.id):.2f}",
            reply_markup=main_menu(),
        )

    elif data == "add_fund":
        context.user_data["state"] = "amount"
        await query.message.reply_text(
            f"💵 Kitna amount add karna hai? Amount enter karein "
            f"(Min ₹{MIN_AMOUNT} - Max ₹{MAX_AMOUNT}):"
        )

    elif data == "submit_ss":
        if "amount" not in context.user_data:
            await query.message.reply_text("Pehle Add Fund se amount enter karein.")
            return
        context.user_data["state"] = "screenshot"
        await query.message.reply_text("📸 Ab payment ka screenshot yahan bhejein.")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "amount":
        await update.message.reply_text("Menu ke liye /start dabayein.")
        return

    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Sahi amount number mein likhein. Jaise: 100")
        return

    if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
        await update.message.reply_text(
            f"❌ Amount ₹{MIN_AMOUNT} se ₹{MAX_AMOUNT} ke beech hona chahiye."
        )
        return

    context.user_data["amount"] = amount
    context.user_data["state"] = None

    qr = make_qr(amount)
    await update.message.reply_photo(
        photo=qr,
        caption=(
            f"💳 Payment Details\n\n"
            f"Amount: ₹{amount:.2f}\n"
            f"UPI ID: {UPI_ID}\n\n"
            "QR scan karke exact amount pay karein, phir neeche "
            "'Submit Screenshot' dabakar screenshot bhejein."
        ),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("📤 Submit Screenshot", callback_data="submit_ss")]]
        ),
    )


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if context.user_data.get("state") != "screenshot":
        await update.message.reply_text(
            "Pehle Add Fund se amount choose karke 'Submit Screenshot' dabayein.",
            reply_markup=main_menu(),
        )
        return

    amount = context.user_data.get("amount")
    photo = update.message.photo[-1]

    try:
        with db() as con:
            cur = con.execute(
                "INSERT INTO payments (user_id, amount, file_id, file_uid) "
                "VALUES (?, ?, ?, ?)",
                (user.id, amount, photo.file_id, photo.file_unique_id),
            )
            pid = cur.lastrowid
    except sqlite3.IntegrityError:
        await update.message.reply_text(
            "❌ Ye screenshot pehle hi submit ho chuka hai."
        )
        return

    context.user_data.clear()

    await update.message.reply_text(
        f"⏳ Payment Pending\n\nAmount: ₹{amount:.2f}\n"
        "Admin approval ke baad amount wallet mein add ho jayega.",
        reply_markup=main_menu(),
    )

    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo.file_id,
        caption=(
            f"🔔 New Payment Request #{pid}\n\n"
            f"User: {user.full_name} (ID: {user.id})\n"
            f"Amount: ₹{amount:.2f}"
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{pid}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{pid}"),
                ]
            ]
        ),
    )


# ---------- Main ----------
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print("Bot chal raha hai...")
    app.run_polling()


if __name__ == "__main__":
    main()
  
