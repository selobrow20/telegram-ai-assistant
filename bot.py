import asyncio
import io
import logging
import os
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile
)

from config import TELEGRAM_BOT_TOKEN, VOICE_REPLY_ENABLED
import database as db
import finance
import gemini_agent
import tts

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("TelegramAIAssistant")

if not TELEGRAM_BOT_TOKEN:
    logger.warning("Peringatan: TELEGRAM_BOT_TOKEN belum diset di .env. Pastikan mengisinya sebelum menjalankan bot.")

# Inisialisasi Dispatcher
dp = Dispatcher()

def get_main_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="💰 Cek Saldo", callback_data="menu_saldo"),
            InlineKeyboardButton(text="📑 Laporan Bulan Ini", callback_data="menu_lap_month")
        ],
        [
            InlineKeyboardButton(text="📅 Laporan Hari Ini", callback_data="menu_lap_today"),
            InlineKeyboardButton(text="⏳ Laporan 7 Hari", callback_data="menu_lap_week")
        ],
        [
            InlineKeyboardButton(text="✅ Daftar To-Do", callback_data="menu_tasks"),
            InlineKeyboardButton(text="📝 Catatan Harian", callback_data="menu_notes")
        ],
        [
            InlineKeyboardButton(text="💡 Contoh Perintah / Bantuan", callback_data="menu_help")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_name = message.from_user.first_name if message.from_user else "Teman"
    welcome_text = (
        f"👋 Halo, *{user_name}*! Saya **Aria**, asisten AI pribadi Anda.\n\n"
        "Saya siap membantu kebutuhan sehari-hari Anda:\n"
        "🎙️ *Interaksi Suara & Teks*: Anda bisa mengetik atau langsung kirim **Voice Note** (pesan suara)!\n"
        "💸 *Catatan Keuangan Otomatis*: Cukup sebutkan pengeluaran/pemasukan Anda.\n"
        "📊 *Laporan Keuangan*: Pantau saldo, arus kas, dan rincian pengeluaran per kategori.\n"
        "📋 *To-Do & Catatan*: Simpan tugas, pengingat, dan ide penting kapan saja.\n"
        "🧠 *AI Bebas*: Tanyakan apa saja, mulai dari draf pesan hingga saran hidup.\n\n"
        "Silakan pilih menu cepat di bawah atau langsung ketik/kirim suara:"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("keuangan"))
async def cmd_keuangan(message: Message):
    user_id = message.from_user.id
    summary = finance.generate_balance_summary(user_id)
    await message.answer(summary, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("laporan"))
async def cmd_laporan(message: Message):
    user_id = message.from_user.id
    report = finance.generate_financial_report(user_id, "month")
    await message.answer(report, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("tugas"))
async def cmd_tugas(message: Message):
    user_id = message.from_user.id
    tasks = db.get_tasks(user_id, status="pending")
    if not tasks:
        await message.answer("🎉 Semua tugas sudah selesai! Belum ada to-do list baru.\n_Ketik 'tambah tugas [nama tugas]' untuk membuat baru._", parse_mode=ParseMode.MARKDOWN)
        return
    lines = ["📋 *DAFTAR TUGAS BELUM SELESAI:*", "━━━━━━━━━━━━━━━━━━━━━━"]
    for t in tasks:
        dl = f" (⏰ {t['due_date']})" if t['due_date'] else ""
        lines.append(f"• [ID #{t['id']}] {t['title']}{dl}")
    lines.append("\n_Ketik 'selesaikan tugas ID' atau 'hapus tugas ID' untuk memperbarui._")
    await message.answer("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("catatan"))
async def cmd_catatan(message: Message):
    user_id = message.from_user.id
    notes = db.get_notes(user_id, limit=10)
    if not notes:
        await message.answer("📝 Belum ada catatan tersimpan.\n_Ketik 'Catat: [isi memo]' untuk menyimpan catatan baru._", parse_mode=ParseMode.MARKDOWN)
        return
    lines = ["📝 *CATATAN TERSIMPAN:*", "━━━━━━━━━━━━━━━━━━━━━━"]
    for n in notes:
        title = f"*{n['title']}*: " if n['title'] else ""
        lines.append(f"• [#{n['id']}] {title}{n['content']} ({n['created_at'][:10]})")
    await message.answer("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("help"))
@dp.message(Command("bantuan"))
async def cmd_help(message: Message):
    help_text = (
        "💡 *PANDUAN PENGGUNAAN ASISTEN AI*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Anda bisa berbicara dengan bahasa santai sehari-hari melalui teks atau pesan suara:\n\n"
        "💰 *Contoh Catat Keuangan:*\n"
        "• _'Tadi makan siang nasi padang 25rb'_\n"
        "• _'Isi bensin motor 35.000'_\n"
        "• _'Dapat transferan gaji 6.000.000'_\n"
        "• _'Sisa uang saya tinggal berapa?'_\n"
        "• _'Buatkan laporan keuangan bulan ini'_\n\n"
        "📋 *Contoh Tugas & Catatan:*\n"
        "• _'Catat tugas beli susu anak pulang kerja nanti'_\n"
        "• _'Ingatkan besok jam 10 pagi ada zoom'_\n"
        "• _'Lihat daftar tugas saya'_\n"
        "• _'Tandai tugas #1 sudah selesai'_\n"
        "• _'Simpan catatan: password wifi kantor xyz123'_\n\n"
        "🎙️ *Pesan Suara (Voice Note):*\n"
        "• Tahan tombol mikrofon di Telegram dan ucapkan pengeluaran atau pertanyaan Anda langsung. AI akan memproses dan membalas dengan teks & suara!\n"
    )
    await message.answer(help_text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query()
async def handle_callbacks(callback: CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id
    await callback.answer()

    if data == "menu_saldo":
        text = finance.generate_balance_summary(user_id)
        await callback.message.answer(text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_lap_month":
        text = finance.generate_financial_report(user_id, "month")
        await callback.message.answer(text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_lap_today":
        text = finance.generate_financial_report(user_id, "today")
        await callback.message.answer(text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_lap_week":
        text = finance.generate_financial_report(user_id, "week")
        await callback.message.answer(text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_tasks":
        tasks = db.get_tasks(user_id, status="pending")
        if not tasks:
            await callback.message.answer("🎉 Semua tugas sudah selesai!", reply_markup=get_main_keyboard())
        else:
            lines = ["📋 *DAFTAR TUGAS AKTIF:*"]
            for t in tasks:
                lines.append(f"• [#{t['id']}] {t['title']}")
            await callback.message.answer("\n".join(lines), reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_notes":
        notes = db.get_notes(user_id, limit=8)
        if not notes:
            await callback.message.answer("📝 Belum ada catatan.", reply_markup=get_main_keyboard())
        else:
            lines = ["📝 *CATATAN:*"]
            for n in notes:
                lines.append(f"• {n['content']}")
            await callback.message.answer("\n".join(lines), reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_help":
        await cmd_help(callback.message)

@dp.message(F.voice)
async def handle_voice_message(message: Message, bot: Bot):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Teman"

    # Indikator bot sedang merekam/memproses
    await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")

    temp_voice_path = None
    try:
        # Download voice note dari Telegram
        file = await bot.get_file(message.voice.file_id)
        voice_io = io.BytesIO()
        await bot.download_file(file.file_path, destination=voice_io)
        voice_bytes = voice_io.getvalue()

        # Proses dengan Gemini AI
        reply_text = await gemini_agent.process_user_voice(
            user_id=user_id,
            user_name=user_name,
            voice_bytes=voice_bytes,
            mime_type="audio/ogg"
        )

        # Kirim balasan teks
        try:
            await message.answer(reply_text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await message.answer(reply_text)

        # Jika suara balasan aktif, buatkan audio balasan TTS
        if VOICE_REPLY_ENABLED:
            try:
                await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")
                audio_file = await tts.text_to_speech_audio(reply_text)
                temp_voice_path = audio_file
                voice_input = FSInputFile(audio_file)
                await message.answer_voice(voice_input)
            except Exception as tts_err:
                logger.error(f"Gagal mengirim balasan suara TTS: {tts_err}")

    except Exception as e:
        logger.error(f"Gagal memproses voice note: {e}", exc_info=True)
        await message.answer(f"Maaf, gagal memproses pesan suara: {e}")
    finally:
        if temp_voice_path:
            tts.cleanup_audio_file(temp_voice_path)

@dp.message(F.text)
async def handle_text_message(message: Message, bot: Bot):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Teman"
    user_text = message.text

    # Indikator typing
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    reply_text = await gemini_agent.process_user_text(
        user_id=user_id,
        user_name=user_name,
        text=user_text
    )

    try:
        await message.answer(reply_text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        # Fallback jika ada karakter format telegram yang escape
        await message.answer(reply_text)

async def main():
    db.init_db()
    logger.info("Database SQLite berhasil diinisialisasi.")
    
    if not TELEGRAM_BOT_TOKEN or len(TELEGRAM_BOT_TOKEN) < 10:
        print("\n" + "="*60)
        print("PERHATIAN: TELEGRAM_BOT_TOKEN belum disetel di file .env!")
        print("Silakan buka file 'd:\\telegram-ai-assistant\\.env' dan masukkan:")
        print("TELEGRAM_BOT_TOKEN=token_bot_anda_dari_BotFather")
        print("GEMINI_API_KEY=kunci_api_gemini_anda")
        print("="*60 + "\n")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logger.info("Menghapus webhook lama jika ada...")
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot Telegram AI Aria siap beroperasi! Menunggu pesan...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
