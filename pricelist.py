import csv
import re
import difflib
import io
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

PRICELIST_PATH = Path("data/pricelist.csv")

def normalize_code(code: str) -> str:
    """Bersihkan kode: lowercase, hapus spasi, tanda hubung, dan tanda baca."""
    if not code:
        return ""
    cleaned = re.sub(r'[^a-zA-Z0-9]', '', code).lower()
    return cleaned

def load_pricelist() -> List[Dict[str, Any]]:
    """Muat seluruh data pricelist dari file CSV."""
    if not PRICELIST_PATH.exists():
        return []
    
    products = []
    with open(PRICELIST_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            products.append(row)
    return products

def format_rupiah_num(val: Any) -> str:
    """Format angka integer/float ke format Rupiah standar: Rp 1.250.000."""
    try:
        clean_val = re.sub(r'[^0-9]', '', str(val))
        if not clean_val:
            return "Rp 0"
        num = int(clean_val)
        return f"Rp {num:,}".replace(",", ".")
    except Exception:
        return f"Rp {val}"

def search_pricelist(query: str, price_tier: str = "ADP") -> Dict[str, Any]:
    """
    Cari produk di pricelist berdasarkan kode, model, atau nama.
    Menerapkan Aturan 1, 2, 3, 4, 5.
    """
    products = load_pricelist()
    if not products:
        return {
            "status": "empty",
            "message": "Data pricelist belum tersedia di database."
        }
    
    q_raw = query.strip()
    q_norm = normalize_code(q_raw)
    
    # 1. Cari exact match (persis sama setelah dinormalisasi)
    for p in products:
        m_norm = normalize_code(p.get("Model", ""))
        if q_norm == m_norm:
            return {
                "status": "exact",
                "product": p,
                "price_tier": price_tier
            }
    
    # 2. Coba tanpa awalan 'rg' jika ada (misal user cari 'ew1200g' -> 'rgew1200g')
    q_no_rg = q_norm[2:] if q_norm.startswith("rg") else q_norm
    for p in products:
        m_norm = normalize_code(p.get("Model", ""))
        m_no_rg = m_norm[2:] if m_norm.startswith("rg") else m_norm
        if q_no_rg == m_no_rg:
            return {
                "status": "exact",
                "product": p,
                "price_tier": price_tier
            }

    # 3. Cari matches awalan / substring
    substring_matches = []
    for p in products:
        m_norm = normalize_code(p.get("Model", ""))
        m_no_rg = m_norm[2:] if m_norm.startswith("rg") else m_norm
        if q_norm in m_norm or q_no_rg in m_no_rg:
            substring_matches.append(p)
            
    if len(substring_matches) == 1:
        return {
            "status": "exact",
            "product": substring_matches[0],
            "price_tier": price_tier
        }
    elif len(substring_matches) > 1 and len(substring_matches) <= 6:
        return {
            "status": "ambiguous",
            "matches": substring_matches,
            "price_tier": price_tier
        }
        
    # 4. Jika tidak ditemukan, gunakan similarity (difflib) untuk 3 kandidat paling mirip
    all_models = [p.get("Model", "") for p in products]
    all_norms = {normalize_code(m): m for m in all_models}
    
    close_norms = difflib.get_close_matches(q_norm, list(all_norms.keys()), n=3, cutoff=0.4)
    if not close_norms:
        # Coba juga pencarian kata kunci pada Description
        desc_matches = []
        words = [w for w in q_raw.lower().split() if len(w) > 2]
        for p in products:
            desc_lower = p.get("Description", "").lower()
            if any(w in desc_lower for w in words):
                desc_matches.append(p)
                if len(desc_matches) >= 3:
                    break
        if desc_matches:
            return {
                "status": "not_found_with_suggestions",
                "query": q_raw,
                "suggestions": [p.get("Model", "") for p in desc_matches]
            }

        return {
            "status": "not_found",
            "query": q_raw,
            "suggestions": []
        }
    
    similar_models = [all_norms[k] for k in close_norms]
    return {
        "status": "not_found_with_suggestions",
        "query": q_raw,
        "suggestions": similar_models[:3]
    }

def format_single_product_answer(product: Dict[str, Any], tier: str = "ADP") -> str:
    """Format jawaban: Tipe dan Harga ADP (Inc PPN) saja tanpa keterangan."""
    model = product.get("Model", "N/A")
    
    # Standar harga: ADP Price (IDR) Inc PPN
    price_val = product.get("Harga_ADP", "0")
    if not price_val or int(price_val or 0) == 0:
        price_val = product.get("Harga_MD", "0")
        
    formatted_price = format_rupiah_num(price_val)
    
    return (
        f"Tipe: {model}\n"
        f"Harga: {formatted_price}"
    )

def query_pricelist_tool(query: str, tier: str = "ADP") -> str:
    """Fungsi pembantu yang dipanggil oleh Gemini Agent atau command bot.
    Mendukung pencarian 1 tipe maupun sekaligus banyak tipe.
    Standar harga: ADP-Price (IDR) Inc PPN.
    """
    # Deteksi apakah query berisi banyak tipe (dipisah newline, koma, semicolon, atau 'dan')
    cleaned = query.replace(";", "\n").replace(",", "\n")
    cleaned = re.sub(r'\s+(?:dan|&)\s+', '\n', cleaned, flags=re.IGNORECASE)
    parts = [p.strip() for p in cleaned.split("\n") if p.strip()]
    
    if len(parts) > 1:
        results = []
        for part in parts:
            p_clean = re.sub(r'^(?:tolong\s+)?(?:carikan\s+)?(?:harga\s+)?(?:adp\s+)?(?:md\s+)?(?:untuk\s+)?', '', part, flags=re.IGNORECASE).strip()
            p_clean = re.sub(r'\s+(?:berapa|dong|ya|unit|pcs)$', '', p_clean, flags=re.IGNORECASE).strip()
            if not p_clean:
                continue
            res = search_pricelist(p_clean, tier)
            st = res.get("status")
            if st == "exact":
                results.append(format_single_product_answer(res["product"], tier))
            elif st == "ambiguous":
                m_list = [f"{m['Model']} ({format_rupiah_num(m.get('Harga_ADP', 0))})" for m in res['matches'][:3]]
                results.append(f"Tipe: {p_clean} (Ambigu: {', '.join(m_list)})")
            elif st == "not_found_with_suggestions" and res.get("suggestions"):
                results.append(f"Tipe: {p_clean} (Tidak ditemukan, opsi: {', '.join(res['suggestions'])})")
            else:
                results.append(f"Tipe: {p_clean} (Tidak ditemukan)")
        return "\n\n".join(results)
    
    # 1 tipe saja
    result = search_pricelist(query, tier)
    st = result.get("status")
    
    if st == "exact":
        return format_single_product_answer(result["product"], result.get("price_tier", "ADP"))
        
    elif st == "ambiguous":
        items = result["matches"]
        lines = [f"Ditemukan beberapa tipe yang mirip dengan '{query}':"]
        for p in items:
            p_price = format_rupiah_num(p.get("Harga_ADP", 0))
            lines.append(f"• Tipe: {p.get('Model')}\n  Harga: {p_price}")
        lines.append("\nMana tipe yang Anda maksud?")
        return "\n".join(lines)
        
    elif st == "not_found_with_suggestions":
        sug = result.get("suggestions", [])
        if sug:
            sug_str = ", ".join(sug)
            return f"Tipe '{query}' tidak ditemukan di pricelist. Mungkin yang Anda maksud: {sug_str}?"
        return f"Tipe '{query}' tidak ditemukan di pricelist."
        
    else:
        return f"Tipe '{query}' tidak ditemukan di pricelist."

def save_new_pricelist_csv(content: str) -> Tuple[bool, str, int]:
    """Menyimpan file CSV pricelist baru yang diupload user."""
    try:
        lines = [l for l in content.strip().splitlines() if l.strip()]
        if len(lines) < 2:
            return False, "File CSV kosong atau tidak memiliki baris data.", 0
        
        header = lines[0].lower()
        if "model" not in header and "tipe" not in header:
            return False, "Format CSV harus memiliki kolom 'Model' atau 'Tipe'.", 0
            
        with open(PRICELIST_PATH, "w", encoding="utf-8") as f:
            f.write(content.strip())
            
        products = load_pricelist()
        return True, f"Pricelist berhasil diperbarui dengan {len(products)} produk.", len(products)
    except Exception as e:
        return False, f"Gagal menyimpan pricelist CSV: {e}", 0

def extract_text_from_excel(doc_bytes: bytes, max_rows: int = 150) -> str:
    """Ekstrak isi teks/tabel dari file Excel (.xlsx) untuk dianalisis oleh AI."""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(doc_bytes), data_only=True)
        sheets_data = []
        for name in wb.sheetnames[:5]:
            ws = wb[name]
            lines = [f"=== Sheet: {name} ==="]
            rows = list(ws.iter_rows(values_only=True))
            for r in rows[:max_rows]:
                if not any(r):
                    continue
                r_str = [str(c) if c is not None else "" for c in r]
                lines.append(" | ".join(r_str))
            if len(rows) > max_rows:
                lines.append(f"... (dan {len(rows) - max_rows} baris lainnya)")
            sheets_data.append("\n".join(lines))
        return "\n\n".join(sheets_data)
    except Exception as e:
        logger.error(f"Gagal ekstrak excel: {e}")
        return ""

def import_pricelist_from_excel(doc_bytes: bytes) -> Tuple[bool, str, int]:
    """Membaca file Excel (.xlsx) dan mengimpor ke data/pricelist.csv jika berisi kolom pricelist."""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(doc_bytes), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows or len(rows) < 2:
            return False, "File Excel kosong atau tidak memiliki baris data.", 0

        header_idx = -1
        header_row = []
        for idx, r in enumerate(rows[:15]):
            r_str = [str(cell or "").lower().strip() for cell in r]
            if any("model" in c or "tipe" in c or "type" in c for c in r_str):
                header_idx = idx
                header_row = r_str
                break

        if header_idx == -1:
            return False, "Bukan format pricelist (kolom Model/Tipe tidak ditemukan).", 0

        col_model = -1
        col_desc = -1
        col_adp = -1
        col_md = -1
        col_installer = -1
        col_online = -1
        col_msrp = -1
        col_warranty = -1

        for i, col_name in enumerate(header_row):
            if "model" in col_name or "tipe" in col_name or "type" in col_name:
                if col_model == -1:
                    col_model = i
            elif "desc" in col_name or "keterangan" in col_name or "deskripsi" in col_name:
                col_desc = i
            elif "adp" in col_name:
                col_adp = i
            elif "bottom" in col_name or "md" in col_name or "dealer" in col_name:
                col_md = i
            elif "installer" in col_name:
                col_installer = i
            elif "online" in col_name or "ref" in col_name:
                col_online = i
            elif "msrp" in col_name or "srp" in col_name or "retail" in col_name:
                col_msrp = i
            elif "warranty" in col_name or "garansi" in col_name:
                col_warranty = i
            elif "harga" in col_name or "price" in col_name:
                if col_adp == -1:
                    col_adp = i

        new_products = []
        for r in rows[header_idx + 1:]:
            if not r or len(r) <= col_model or not r[col_model]:
                continue
            model = str(r[col_model]).strip()
            if not model or model.lower() in ("none", "model", "tipe", "type"):
                continue
            desc = str(r[col_desc]).strip() if col_desc != -1 and len(r) > col_desc and r[col_desc] else ""

            def clean_num(val):
                if not val:
                    return "0"
                c = re.sub(r'[^0-9]', '', str(val))
                return c if c else "0"

            adp = clean_num(r[col_adp]) if col_adp != -1 and len(r) > col_adp else "0"
            md = clean_num(r[col_md]) if col_md != -1 and len(r) > col_md else adp
            installer = clean_num(r[col_installer]) if col_installer != -1 and len(r) > col_installer else "0"
            online = clean_num(r[col_online]) if col_online != -1 and len(r) > col_online else "0"
            msrp = clean_num(r[col_msrp]) if col_msrp != -1 and len(r) > col_msrp else "0"
            warranty = str(r[col_warranty]).strip() if col_warranty != -1 and len(r) > col_warranty and r[col_warranty] else "3 Years Warranty"

            new_products.append({
                "Model": model,
                "Description": desc,
                "Harga_MD": md if int(md or 0) > 0 else adp,
                "Harga_ADP": adp if int(adp or 0) > 0 else md,
                "Harga_Installer": installer,
                "Harga_Online": online,
                "Harga_MSRP": msrp,
                "Warranty": warranty
            })

        if not new_products:
            return False, "Tidak ada data produk yang berhasil diekstrak.", 0

        with open(PRICELIST_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["Model", "Description", "Harga_MD", "Harga_ADP", "Harga_Installer", "Harga_Online", "Harga_MSRP", "Warranty"])
            writer.writeheader()
            writer.writerows(new_products)

        return True, f"Berhasil mengimpor {len(new_products)} produk ke database pricelist.", len(new_products)
    except Exception as e:
        return False, f"Gagal membaca file Excel: {e}", 0

def update_product_price(model_query: str, new_price: Any) -> Tuple[bool, str]:
    """Mengubah atau memperbarui harga suatu produk di data/pricelist.csv."""
    clean_price = re.sub(r'[^0-9]', '', str(new_price))
    if not clean_price:
        return False, "Nominal harga tidak valid."

    products = load_pricelist()
    q_norm = normalize_code(model_query)

    found = False
    updated_model = ""
    for p in products:
        m_norm = normalize_code(p.get("Model", ""))
        if q_norm == m_norm or (q_norm.startswith("rg") and q_norm[2:] == m_norm[2:]) or (q_norm.startswith("dh") and q_norm[2:] == m_norm[2:]):
            p["Harga_ADP"] = clean_price
            p["Harga_MD"] = clean_price
            updated_model = p.get("Model", model_query)
            found = True
            break

    if not found:
        for p in products:
            m_norm = normalize_code(p.get("Model", ""))
            if q_norm in m_norm:
                p["Harga_ADP"] = clean_price
                p["Harga_MD"] = clean_price
                updated_model = p.get("Model", model_query)
                found = True
                break

    if not found:
        return False, f"Produk '{model_query}' tidak ditemukan di database pricelist."

    fieldnames = ["Model", "Description", "Harga_MD", "Harga_ADP", "Harga_Installer", "Harga_Online", "Harga_MSRP", "Warranty", "Brand"]
    with open(PRICELIST_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(products)

    return True, f"✅ Harga {updated_model} berhasil diupdate menjadi {format_rupiah_num(clean_price)}."
