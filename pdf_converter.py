import io
import json
import logging
import os
import re
import uuid
import time
from pathlib import Path
from typing import Tuple, Dict, Any, Optional

import pypdf
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from config import DATA_DIR, GEMINI_API_KEY
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

EXPORTS_DIR = DATA_DIR / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)

# Registry untuk menyimpan file Excel dari PDF terakhir per pengguna:
user_last_pdf: Dict[int, Dict[str, Any]] = {}

def extract_text_from_pdf(doc_bytes: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(doc_bytes))
        pages = []
        for i, page in enumerate(reader.pages):
            txt = page.extract_text() or ""
            if txt.strip():
                pages.append(f"[Halaman {i+1}]:\n{txt.strip()}")
        return "\n\n".join(pages)
    except Exception as e:
        logger.error(f"Gagal ekstraksi teks PDF: {e}")
        return ""

def sanitize_sheet_title(name: str) -> str:
    cleaned = re.sub(r'[\\/*?:\[\]]', '_', str(name)).strip()
    return cleaned[:30] if cleaned else "Sheet1"

def create_excel_from_structured_data(data: Dict[str, Any], output_path: str):
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Ringkasan Laporan"
    ws1.views.sheetView[0].showGridLines = True

    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Calibri", size=14, bold=True, color="1E3A8A")
    regular_font = Font(name="Calibri", size=11)
    bold_font = Font(name="Calibri", size=11, bold=True)
    thin_border = Border(
        left=Side(style='thin', color='D1D5DB'),
        right=Side(style='thin', color='D1D5DB'),
        top=Side(style='thin', color='D1D5DB'),
        bottom=Side(style='thin', color='D1D5DB')
    )

    ws1['A1'] = data.get('title', 'Laporan Hasil Konversi PDF')
    ws1['A1'].font = title_font

    ws1.cell(row=3, column=1, value="Parameter / Rincian").font = header_font
    ws1.cell(row=3, column=1).fill = header_fill
    ws1.cell(row=3, column=2, value="Nilai / Keterangan").font = header_font
    ws1.cell(row=3, column=2).fill = header_fill

    row = 4
    summary_items = data.get('summary', [])
    if not summary_items:
        summary_items = [
            {"label": "Status", "value": "Data laporan berhasil diekstrak"},
            {"label": "Judul", "value": data.get('title', 'Laporan PDF')}
        ]

    for item in summary_items:
        ws1.cell(row=row, column=1, value=str(item.get('label', ''))).font = bold_font
        c2 = ws1.cell(row=row, column=2, value=str(item.get('value', '')))
        c2.font = regular_font
        ws1.cell(row=row, column=1).border = thin_border
        ws1.cell(row=row, column=2).border = thin_border
        row += 1

    # Format lebar kolom summary
    for col in ws1.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = max(max_len + 4, 18)

    # Tambahkan sheet tabel rincian jika ada
    tables = data.get('tables', [])
    used_titles = {"Ringkasan Laporan"}

    for idx, table in enumerate(tables):
        raw_name = str(table.get('name', f'Data Detail {idx+1}'))
        t_name = sanitize_sheet_title(raw_name)
        if t_name in used_titles:
            t_name = sanitize_sheet_title(f"{t_name[:25]}_{idx+1}")
        used_titles.add(t_name)

        ws = wb.create_sheet(title=t_name)
        ws.views.sheetView[0].showGridLines = True

        headers = table.get('headers', [])
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=str(h))
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for r_idx, r_data in enumerate(table.get('rows', []), 2):
            for c_idx, val in enumerate(r_data, 1):
                c = ws.cell(row=r_idx, column=c_idx, value=str(val))
                c.font = regular_font
                c.border = thin_border

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    wb.save(output_path)

async def convert_pdf_document_to_excel(doc_bytes: bytes, file_name: str, caption: str = "", user_id: Optional[int] = None) -> Tuple[str, str]:
    client = genai.Client(api_key=GEMINI_API_KEY)
    extracted_text = extract_text_from_pdf(doc_bytes)

    prompt = (
        f"Anda adalah sistem AI ahli ekstraksi data dokumen dan pelaporan spreadsheet Excel (.xlsx).\n"
        f"Dokumen: {file_name}. Catatan/Caption pengguna: '{caption}'\n\n"
        f"TUGAS UTAMA:\n"
        f"1. Analisis seluruh teks, tabel, angka, dan komponen dari dokumen PDF ini secara cermat.\n"
        f"2. Ekstrak data menjadi struktur JSON yang valid dan lengkap untuk dibuatkan file spreadsheet Excel multi-sheet.\n"
        f"3. Pada 'summary': masukkan ringkasan metrik utama (seperti Judul, Periode, Total Omzet/Pemasukan, Total Pengeluaran/Biaya, Laba Bersih, Jumlah Pesanan, Kategori Terlaris, dll).\n"
        f"4. Pada 'tables': ekstrak SELURUH data rincian/transaksi/tabel yang ditemukan ke dalam tabel (memiliki 'name', 'headers', dan 'rows'). Pastikan semua angka, rincian biaya, atau transaksi dimasukkan secara lengkap baris demi baris.\n"
        f"5. Pada 'executive_summary': buat ringkasan profesional dalam bahasa Indonesia dengan format rapi (bullet points) yang menjelaskan performa laporan ini untuk dibaca pengguna di Telegram.\n\n"
        f"WAJIB KELUARKAN DALAM FORMAT JSON SEPERTI CONTOH BERIKUT:\n"
        f"{{\n"
        f'  "title": "Laporan Penjualan / Performa Printing",\n'
        f'  "summary": [\n'
        f'    {{"label": "Total Omzet", "value": "Rp 3.180.542"}},\n'
        f'    {{"label": "Total Pengeluaran", "value": "Rp 845.000"}},\n'
        f'    {{"label": "Laba Bersih", "value": "Rp 2.335.542"}}\n'
        f'  ],\n'
        f'  "tables": [\n'
        f'    {{\n'
        f'      "name": "Rincian Transaksi",\n'
        f'      "headers": ["No", "Tanggal", "Keterangan", "Kategori", "Jumlah / Biaya"],\n'
        f'      "rows": [\n'
        f'        ["1", "2026-09-01", "Art Carton 210", "Bahan Baku", "496 lembar"]\n'
        f'      ]\n'
        f'    }}\n'
        f'  ],\n'
        f'  "executive_summary": "Rangkuman lengkap..."\n'
        f"}}\n"
    )

    if extracted_text:
        prompt += f"\n\nTEKS DIGITAL TERDETEKSI:\n{extracted_text[:12000]}"

    parts = []
    # Kirimkan bytes PDF langsung agar Gemini membaca visual/tabel layout dokumen
    try:
        parts.append(types.Part.from_bytes(data=doc_bytes, mime_type="application/pdf"))
    except Exception as e:
        logger.warning(f"Gagal melampirkan doc_bytes ke types.Part: {e}")
    parts.append(types.Part.from_text(text=prompt))

    models_to_try = [
        "gemini-3.1-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
        "gemini-3.5-flash-lite"
    ]

    response_text = ""
    for m in models_to_try:
        try:
            resp = client.models.generate_content(
                model=m,
                contents=parts,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json"
                )
            )
            response_text = resp.text or ""
            if response_text:
                break
        except Exception as e:
            logger.warning(f"Model {m} kendala saat ekstraksi PDF ke Excel: {e}")
            continue

    # Fallback jika model dengan parts gagal, coba hanya teks
    if not response_text and extracted_text:
        for m in models_to_try:
            try:
                resp = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        response_mime_type="application/json"
                    )
                )
                response_text = resp.text or ""
                if response_text:
                    break
            except Exception:
                continue

    # Parsing JSON dari respon Gemini
    parsed_data = None
    if response_text:
        # Hapus markdown jika ada
        clean_json = re.sub(r'^```(?:json)?\s*', '', response_text.strip())
        clean_json = re.sub(r'\s*```$', '', clean_json).strip()
        try:
            parsed_data = json.loads(clean_json)
        except Exception as pe:
            logger.warning(f"JSON parsing error: {pe}")

    if not parsed_data or not isinstance(parsed_data, dict):
        # Fallback terstruktur jika Gemini gagal parse
        clean_lines = [l.strip() for l in extracted_text.splitlines() if l.strip()]
        parsed_data = {
            "title": f"Laporan {Path(file_name).stem}",
            "summary": [
                {"label": "Nama Dokumen", "value": file_name},
                {"label": "Status", "value": "Berhasil diekstrak ke Excel"}
            ],
            "tables": [{
                "name": "Rincian Dokumen",
                "headers": ["No", "Baris / Cuplikan Teks"],
                "rows": [[str(idx+1), line] for idx, line in enumerate(clean_lines[:100])]
            }],
            "executive_summary": (
                f"📄 *LAPORAN DOKUMEN: {file_name}*\n\n"
                f"File PDF telah berhasil diproses dan dikonversi menjadi spreadsheet Excel (.xlsx). "
                f"Rincian isi laporan telah disusun rapi di lembar kerja Excel terlampir."
            )
        }

    clean_name = re.sub(r'[^a-zA-Z0-9_-]', '_', Path(file_name).stem)
    out_file = EXPORTS_DIR / f"Laporan_{clean_name}_{uuid.uuid4().hex[:6]}.xlsx"
    create_excel_from_structured_data(parsed_data, str(out_file))

    summary_text = parsed_data.get('executive_summary', '')
    if not summary_text or len(summary_text) < 15:
        summary_text = (
            f"📄 *LAPORAN TELAH BERHASIL DIKONVERSI KE EXCEL*\n\n"
            f"• **Dokumen:** `{file_name}`\n"
            f"• **Judul:** {parsed_data.get('title', file_name)}\n"
            f"• **Status:** File spreadsheet Excel (.xlsx) telah dibuat khusus dari PDF ini secara terpisah tanpa mengubah database catatan harian Anda."
        )

    # Simpan ke registry jika user_id diberikan
    if user_id:
        user_last_pdf[user_id] = {
            "excel_path": str(out_file),
            "file_name": file_name,
            "title": parsed_data.get('title', file_name),
            "created_at": time.time()
        }

    return summary_text, str(out_file)
