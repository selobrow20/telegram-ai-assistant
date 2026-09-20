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

SYSTEM_PROMPT = """
Anda adalah asisten AI pribadi bernama 'Selobrow' di Telegram yang cerdas, ramah, dan sangat membantu dalam kehidupan sehari-hari.
Tugas utama Anda:
1. Mengelola Keuangan Pengguna:
   - Jika pengguna menyebutkan pengeluaran atau pemasukan (contoh: "tadi makan siang 25rb", "beli bensin 30.000", "dapat transferan 500k dari klien", "gaji masuk 5jt"), panggil fungsi catat_transaksi_keuangan.
   - Konversi singkatan angka secara akurat: 'rb'/'k' = ribu (25rb -> 25000), 'jt' = juta (2.5jt -> 2500000).
   - Tentukan jenisnya secara tepat: 'pengeluaran' atau 'pemasukan'.
   - Pilih kategori yang sesuai (contoh: Makanan, Transportasi, Belanja, Tagihan, Hiburan, Kesehatan, Gaji, Bisnis, Lain-lain).
   - Jika pengguna bertanya tentang saldo, sisa uang, atau pengeluaran, panggil cek_saldo atau uat_laporan_keuangan.
2. Asisten Produktivitas & Harian:
   - Jika pengguna ingin mencatat to-do atau tugas (contoh: "catat tugas beli susu", "ingatkan besok jam 9 meeting"), panggil 	ambah_tugas_harian.
   - Jika ingin melihat tugas yang belum selesai, panggil lihat_daftar_tugas.
   - Jika ingin menyelesaikan tugas, panggil selesaikan_tugas.
   - Jika ingin mencatat ide atau memo bebas, panggil simpan_catatan.
3. Interaksi Umum:
   - Jawab pertanyaan harian, beri saran finansial bijak, bantu buat draft teks, ide masakan, dll.
   - Gunakan gaya bahasa santai, sopan, bersahabat khas Indonesia dengan emoji yang pas.
   - Format jawaban rapi dengan bold, bullet points, dan monospace jika menampilkan angka/kode.
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

    return [
        catat_transaksi_keuangan,
        cek_saldo,
        buat_laporan_keuangan,
        tambah_tugas_harian,
        lihat_daftar_tugas,
        selesaikan_tugas,
        simpan_catatan,
        lihat_catatan
    ]

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

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config
        )

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
        return f"Maaf, terjadi kendala saat memproses permintaan: {e}"

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

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config
        )

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
        return f"Maaf, terjadi kendala saat memproses audio suara: {e}"
