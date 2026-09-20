import logging
from typing import Dict, Any, List
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_MODEL
import database as db
import finance

logger = logging.getLogger(__name__)

# Simpan riwayat obrolan per user: {user_id: [types.Content, ...]}
user_histories: Dict[int, List[types.Content]] = {}
MAX_HISTORY = 12

def get_client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY belum disetel! Harap isi di file .env")
    return genai.Client(api_key=GEMINI_API_KEY)

def clear_user_history(user_id: int):
    user_histories.pop(user_id, None)

SYSTEM_PROMPT = """
Anda adalah asisten AI pribadi bernama 'Selobrow' di Telegram yang cerdas, ramah, dan sangat membantu dalam kehidupan sehari-hari.
PENTING: Nama Anda adalah 'Selobrow', BUKAN Aria. Selalu perkenalkan dan sebut diri Anda sebagai Selobrow.

KEMAMPUAN UTAMA ANDA:
1. MEMBACA & MENGANALISIS DOKUMEN PDF:
   - Anda BISA dan MAMPU membaca file PDF (laporan keuangan, invoice tagihan, mutasi rekening bank, rekap transaksi, dan dokumen bisnis).
   - Jika pengguna bertanya apakah Anda bisa membaca file PDF, JAWAB DENGAN YAKIN: "Bisa banget! Silakan langsung kirimkan file PDF laporan atau invoice Anda ke sini, saya akan baca dan buatkan ringkasan lengkapnya, serta data keuangan di bot ini juga bisa diunduh ke format Excel (.xlsx)."
2. MEMINDAI FOTO STRUK / NOTA / KWITANSI:
   - Anda BISA membaca dan menganalisis foto struk belanjaan (Indomaret, Alfamart, SPBU, cafe, resto, nota belanja).
   - Anda otomatis mengenali merchant, rincian barang, total pembayaran, dan mencatatnya ke pembukuan keuangan.
3. MENGELOLA KEUANGAN & EKSPOR EXCEL:
   - Jika pengguna menyebutkan pengeluaran/pemasukan ("makan 25rb", "beli bensin 35k", "transfer 500k"), panggil `catat_transaksi_keuangan`.
   - Konversi singkatan angka secara akurat: 'rb'/'k' = ribu (25rb -> 25000), 'jt' = juta (2.5jt -> 2500000).
   - Tentukan jenisnya secara tepat: 'pengeluaran' atau 'pemasukan'.
   - Jika pengguna bertanya saldo atau laporan, panggil `cek_saldo` atau `buat_laporan_keuangan`.
   - Pengguna bisa mengunduh file spreadsheet Excel (.xlsx) dengan tombol 'Download Excel' atau command /excel.
4. ASISTEN PRODUKTIVITAS & HARIAN:
   - Catat to-do list (`tambah_tugas_harian`), lihat to-do (`lihat_daftar_tugas`), selesai (`selesaikan_tugas`).
   - Simpan memo/catatan harian (`simpan_catatan`), lihat memo (`lihat_catatan`).
5. INTERAKSI UMUM:
   - Selalu ramah, gunakan bahasa Indonesia yang santai, sopan, bersahabat dengan emoji yang pas.
"""

def create_tools_for_user(user_id: int):
    def catat_transaksi_keuangan(tipe: str, nominal: float, kategori: str, keterangan: str = "") -> str:
        """Mencatat pemasukan atau pengeluaran keuangan ke database.
        Args:
            tipe: 'pengeluaran' atau 'pemasukan'
            nominal: Jumlah uang dalam angka Rupiah (misal 50000)
            kategori: Kategori transaksi (misal: Makanan, Transportasi, Belanja, Tagihan, Gaji, dll)
            keterangan: Rincian transaksi (misal: 'Nasi goreng dan es teh')
        """
        t_type = "income" if "masuk" in tipe.lower() or "income" in tipe.lower() else "expense"
        trans_id = db.add_transaction(user_id, t_type, nominal, kategori, keterangan)
        bal = db.get_balance(user_id)
        fmt_nominal = finance.format_rupiah(nominal)
        fmt_saldo = finance.format_rupiah(bal['balance'])
        jenis_str = "Pemasukan" if t_type == "income" else "Pengeluaran"
        return f"Berhasil mencatat {jenis_str} sebesar {fmt_nominal} (Kategori: {kategori}, Ket: {keterangan}). ID Transaksi: {trans_id}. Sisa Saldo saat ini: {fmt_saldo}."

    def cek_saldo() -> str:
        """Mengecek ringkasan saldo keuangan pengguna saat ini (total pemasukan, pengeluaran, dan saldo bersih)."""
        return finance.generate_balance_summary(user_id)

    def buat_laporan_keuangan(periode: str = "month") -> str:
        """Membuat laporan keuangan lengkap berdasarkan periode.
        Args:
            periode: Pilihan periode ('today' untuk hari ini, 'week' untuk minggu ini, 'month' untuk bulan ini, 'all' untuk semua waktu)
        """
        return finance.generate_financial_report(user_id, periode)

    def tambah_tugas_harian(judul_tugas: str, batas_waktu: str = "") -> str:
        """Menambahkan tugas baru atau to-do list harian pengguna.
        Args:
            judul_tugas: Deskripsi tugas/kegiatan yang harus dilakukan
            batas_waktu: Waktu atau tanggal deadline (opsional, contoh: 'Besok jam 9 pagi')
        """
        task_id = db.add_task(user_id, judul_tugas, batas_waktu if batas_waktu else None)
        return f"Tugas berhasil disimpan dengan ID #{task_id}: '{judul_tugas}'" + (f" (Deadline: {batas_waktu})" if batas_waktu else "")

    def lihat_daftar_tugas(status: str = "pending") -> str:
        """Melihat daftar tugas / to-do list.
        Args:
            status: 'pending' untuk tugas yang belum selesai, 'completed' untuk yang sudah selesai, atau 'all' untuk semua
        """
        st = None if status == "all" else status
        tasks = db.get_tasks(user_id, st)
        if not tasks:
            return "Tidak ada tugas dalam daftar saat ini. Semua beres!"
        res = "Daftar Tugas:\n"
        for t in tasks:
            icon = "✅" if t['status'] == 'completed' else "⏳"
            dl = f" (Deadline: {t['due_date']})" if t['due_date'] else ""
            res += f"- [#{t['id']}] {icon} {t['title']}{dl}\n"
        return res

    def selesaikan_tugas(task_id: int) -> str:
        """Menandai suatu tugas sebagai telah selesai berdasarkan ID tugas.
        Args:
            task_id: Angka ID tugas
        """
        ok = db.update_task_status(user_id, task_id, "completed")
        if ok:
            return f"Hebat! Tugas #{task_id} berhasil ditandai selesai."
        return f"Tugas dengan ID #{task_id} tidak ditemukan."

    def simpan_catatan(judul: str, isi_catatan: str) -> str:
        """Menyimpan memo atau catatan harian bebas.
        Args:
            judul: Judul memo/catatan
            isi_catatan: Isi lengkap teks catatan
        """
        nid = db.add_note(user_id, isi_catatan, judul)
        return f"Catatan '{judul}' berhasil disimpan dengan ID #{nid}."

    def lihat_catatan() -> str:
        """Melihat catatan atau memo harian yang pernah disimpan."""
        notes = db.get_notes(user_id, limit=10)
        if not notes:
            return "Belum ada catatan yang tersimpan."
        res = "Catatan Tersimpan:\n"
        for n in notes:
            t = f"*{n['title']}*: " if n['title'] else ""
            res += f"- [#{n['id']}] {t}{n['content']} ({n['created_at'][:10]})\n"
        return res

    def catat_banyak_transaksi(daftar_transaksi: list) -> str:
        """Mencatat banyak transaksi keuangan sekaligus ke database (berguna saat membaca tabel PDF laporan, mutasi, atau rekap penjualan).
        Args:
            daftar_transaksi: List of dicts, masing-masing memuat 'type' ('pemasukan'/'pengeluaran'), 'amount' (angka rupiah), 'category' (kategori), dan 'description' (keterangan).
        """
        count = db.add_multiple_transactions(user_id, daftar_transaksi)
        bal = db.get_balance(user_id)
        return f"Berhasil menyimpan {count} transaksi ke database. Total Pemasukan: {finance.format_rupiah(bal['total_income'])}, Total Pengeluaran: {finance.format_rupiah(bal['total_expense'])}, Saldo: {finance.format_rupiah(bal['balance'])}."

    return [
        catat_transaksi_keuangan,
        catat_banyak_transaksi,
        cek_saldo,
        buat_laporan_keuangan,
        tambah_tugas_harian,
        lihat_daftar_tugas,
        selesaikan_tugas,
        simpan_catatan,
        lihat_catatan
    ]

def generate_with_fallback(client: genai.Client, contents: list, config: types.GenerateContentConfig):
    models = [
        "gemini-3.1-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-flash-latest",
        "gemini-3.5-flash"
    ]
    last_error = None
    for m in models:
        try:
            return client.models.generate_content(
                model=m,
                contents=contents,
                config=config
            )
        except Exception as err:
            last_error = err
            err_msg = str(err)
            logger.warning(f"Model {m} kendala: {err_msg[:80]}. Mencoba model cadangan...")
            if any(k in err_msg for k in ["429", "RESOURCE_EXHAUSTED", "503", "NOT_FOUND", "404"]):
                continue
            raise err
    raise last_error

def format_friendly_error(e: Exception) -> str:
    err = str(e)
    if "429" in err or "RESOURCE_EXHAUSTED" in err:
        return "⚡ *Batas Kecepatan Tercapai (Rate Limit)*\n\nGoogle Gemini membatasi kecepatan permintaan akun gratis per menit. Mohon tunggu sekitar **5–10 detik** lalu kirim kembali pesan Anda ya!"
    elif "503" in err or "UNAVAILABLE" in err:
        return "⏳ *Server AI Sedang Sibuk*\n\nServer Google sedang mengalami lonjakan antrean. Mohon tunggu sebentar lalu coba lagi."
    return f"Maaf, terjadi kendala saat memproses: {err[:140]}"

async def process_user_text(user_id: int, user_name: str, text: str) -> str:
    try:
        client = get_client()
        tools = create_tools_for_user(user_id)
        
        history = user_histories.setdefault(user_id, [])
        user_content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"[User: {user_name}]\n{text}")]
        )
        
        # Build contents payload
        contents = list(history) + [user_content]

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=tools,
            temperature=0.7
        )

        response = generate_with_fallback(client, contents, config)

        reply_text = response.text or "Baik, sudah diproses!"

        # Update user history
        model_content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=reply_text)]
        )
        history.append(user_content)
        history.append(model_content)

        if len(history) > MAX_HISTORY:
            user_histories[user_id] = history[-MAX_HISTORY:]

        return reply_text
    except Exception as e:
        logger.error(f"Error in process_user_text: {e}", exc_info=True)
        return format_friendly_error(e)

async def process_user_voice(user_id: int, user_name: str, voice_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    try:
        client = get_client()
        tools = create_tools_for_user(user_id)
        
        audio_part = types.Part.from_bytes(data=voice_bytes, mime_type=mime_type)
        instruction_part = types.Part.from_text(
            text=f"[User: {user_name} mengirim pesan suara]. Dengarkan pesan suara ini secara saksama, pahami maksudnya, jalankan alat/fungsi jika ada transaksi/tugas/catatan, lalu berikan jawaban yang ramah dan relevan."
        )

        history = user_histories.setdefault(user_id, [])
        user_content = types.Content(
            role="user",
            parts=[audio_part, instruction_part]
        )
        contents = list(history) + [user_content]

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=tools,
            temperature=0.7
        )

        response = generate_with_fallback(client, contents, config)

        reply_text = response.text or "Pesan suara Anda telah saya dengarkan dan saya proses."

        model_content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=reply_text)]
        )
        history.append(user_content)
        history.append(model_content)

        if len(history) > MAX_HISTORY:
            user_histories[user_id] = history[-MAX_HISTORY:]

        return reply_text
    except Exception as e:
        logger.error(f"Error in process_user_voice: {e}", exc_info=True)
        return format_friendly_error(e)

async def process_user_image(user_id: int, user_name: str, image_bytes: bytes, mime_type: str = "image/jpeg", caption: str = "") -> str:
    try:
        client = get_client()
        tools = create_tools_for_user(user_id)

        prompt_text = (
            f"[User: {user_name} mengirim foto/gambar]. Caption pengguna: '{caption if caption else 'Tidak ada'}'\n"
            "Analisis gambar tersebut secara teliti.\n"
            "JIKA GAMBAR ADALAH STRUK BELANJA, NOTA, KWITANSI, ATAU TIKET:\n"
            "1. Identifikasi nama toko/merchant (misal: Indomaret, Alfamart, SPBU, Cafe, Resto, dll).\n"
            "2. Identifikasi tanggal & jam jika ada.\n"
            "3. Rinci barang/item yang dibeli beserta harganya.\n"
            "4. Cari JUMLAH TOTAL AKHIR (Grand Total) pembayaran.\n"
            "5. WAJIB PANGGIL fungsi `catat_transaksi_keuangan` untuk mencatat nominal total tersebut sebagai pengeluaran dengan kategori yang sesuai (misal: Makanan, Belanja, Transportasi, Kesehatan, dsb).\n"
            "6. Berikan balasan yang rapi dan terstruktur: Nama Merchant, Tanggal, Rincian Barang, Total Nominal, dan konfirmasi bahwa transaksi sudah berhasil dicatat otomatis.\n"
            "JIKA GAMBAR LAIN (Grafik/Foto/Teks): Jelaskan isi gambar dan jawab sesuai caption/pertanyaan pengguna."
        )

        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        instruction_part = types.Part.from_text(text=prompt_text)

        history = user_histories.setdefault(user_id, [])
        user_content = types.Content(
            role="user",
            parts=[image_part, instruction_part]
        )
        contents = list(history) + [user_content]

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=tools,
            temperature=0.4
        )

        response = generate_with_fallback(client, contents, config)

        reply_text = response.text or "Foto berhasil dianalisis."

        model_content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=reply_text)]
        )
        history.append(user_content)
        history.append(model_content)

        if len(history) > MAX_HISTORY:
            user_histories[user_id] = history[-MAX_HISTORY:]

        return reply_text
    except Exception as e:
        logger.error(f"Error in process_user_image: {e}", exc_info=True)
        return format_friendly_error(e)

async def process_user_document(user_id: int, user_name: str, doc_bytes: bytes, file_name: str, mime_type: str = "application/pdf", caption: str = "") -> str:
    try:
        client = get_client()
        tools = create_tools_for_user(user_id)

        # Ekstraksi teks digital dari PDF menggunakan pypdf
        extracted_text = ""
        try:
            import pypdf
            import io
            reader = pypdf.PdfReader(io.BytesIO(doc_bytes))
            pages = []
            for i, page in enumerate(reader.pages):
                txt = page.extract_text() or ""
                if txt.strip():
                    pages.append(f"[Halaman {i+1}]:\n{txt.strip()}")
            if pages:
                extracted_text = "\n\n".join(pages)
        except Exception as pe:
            logger.warning(f"Ekstraksi teks pypdf: {pe}")

        prompt_text = (
            f"[User: {user_name} mengirim file dokumen: {file_name}]. Caption: '{caption if caption else 'Analisis dan masukkan ke pembukuan'}'\n"
            "Analisis dokumen PDF ini secara mendalam:\n"
            "1. Pahami isi utama laporan, omzet penjualan, mutasi rekening, invoice, atau laporan keuangan di dalamnya.\n"
            "2. Berikan ringkasan eksekutif yang jelas dan terstruktur dalam format bullet points rapi (Omzet/Pendapatan, Pengeluaran, Laba Bersih, Catatan Operasional).\n"
            "3. PENTING & WAJIB: Jika dokumen PDF memuat ringkasan keuangan (seperti Total Omzet/Pemasukan dan Total Pengeluaran/Modal) atau rincian transaksi, SEGERA PANGGIL fungsi `catat_transaksi_keuangan` atau `catat_banyak_transaksi` untuk LANGSUNG MEMASUKKAN angka-angka tersebut ke database pembukuan keuangan!\n"
            "   - Contoh: Catat Total Uang Masuk sebagai 'pemasukan' kategori 'Penjualan' (misal dari Shopee/Klien), dan Total Uang Keluar sebagai 'pengeluaran' kategori 'Operasional'.\n"
            "4. Informasikan ke pengguna bahwa data omzet dan pengeluaran dari PDF tersebut SUDAH BERHASIL TERCATAT ke database dan otomatis langsung masuk ke file spreadsheet Excel (.xlsx) saat mengetik /excel."
        )

        if extracted_text:
            prompt_text += f"\n\nTEKS ISI DOKUMEN:\n{extracted_text[:15000]}"

        parts = [types.Part.from_text(text=prompt_text)]
        try:
            parts.append(types.Part.from_bytes(data=doc_bytes, mime_type=mime_type))
        except Exception:
            pass

        history = user_histories.setdefault(user_id, [])
        user_content = types.Content(
            role="user",
            parts=parts
        )
        contents = list(history) + [user_content]

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=tools,
            temperature=0.4
        )

        response = generate_with_fallback(client, contents, config)

        reply_text = response.text or "Dokumen PDF telah berhasil dianalisis."

        model_content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=reply_text)]
        )
        history.append(user_content)
        history.append(model_content)

        if len(history) > MAX_HISTORY:
            user_histories[user_id] = history[-MAX_HISTORY:]

        return reply_text
    except Exception as e:
        logger.error(f"Error in process_user_document: {e}", exc_info=True)
        return format_friendly_error(e)

