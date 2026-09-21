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
    
    # 2. Coba tanpa awalan brand jika ada ('dhi', 'dh', 'ids', 'ds', 'rg', 'reyee', 'hilook', 'hiview', 'thc', 'ipc', 'th', 'hv', 'hik')
    def strip_brand_pfx(s: str) -> str:
        for pfx in ['reyee', 'dhi', 'dh', 'ids', 'ds', 'rg', 'hilook', 'hiview', 'thc', 'ipc', 'th', 'hv', 'hik']:
            if s.startswith(pfx):
                return s[len(pfx):]
        return s

    q_stripped = strip_brand_pfx(q_norm)
    for p in products:
        m_norm = normalize_code(p.get("Model", ""))
        m_stripped = strip_brand_pfx(m_norm)
        if q_stripped == m_stripped:
            return {
                "status": "exact",
                "product": p,
                "price_tier": price_tier
            }

    # 3. Cari matches awalan / substring
    substring_matches = []
    for p in products:
        m_norm = normalize_code(p.get("Model", ""))
        m_stripped = strip_brand_pfx(m_norm)
        if q_norm in m_norm or (len(q_stripped) >= 3 and q_stripped in m_stripped):
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
    """Format: Model dan Harga saja untuk semua tipe dan merek."""
    model = product.get("Model", "N/A")
    brand = product.get("Brand", "General")
    
    tier_upper = tier.upper() if tier else ""
    
    if brand.lower() == "hikvision":
        price_val = product.get("Harga_DPP") or product.get("Harga_ADP") or product.get("Harga_MD")
    elif brand.lower() == "dahua":
        price_val = product.get("Harga_MDP") or product.get("Harga_MD") or product.get("Harga_ADP")
    elif brand.lower() == "ruijie":
        price_val = product.get("Harga_ADP") or product.get("Harga_MD")
    elif brand.lower() == "hilook":
        price_val = product.get("Harga_MD") or product.get("Harga_ADP") or product.get("Harga_MSRP")
    elif brand.lower() == "hiview":
        price_val = product.get("Harga_MD") or product.get("Harga_ADP") or product.get("Harga_MSRP")
    else:
        price_val = product.get("Harga_ADP") or product.get("Harga_MD") or product.get("Harga_MSRP")

    if tier_upper == "MSRP" and product.get("Harga_MSRP"):
        price_val = product.get("Harga_MSRP")
    elif tier_upper in ("NON-DPP", "NONDPP") and product.get("Harga_Non_DPP"):
        price_val = product.get("Harga_Non_DPP")
    elif tier_upper in ("DEALER", "MD") and product.get("Harga_MD"):
        price_val = product.get("Harga_MD")

    if not price_val or str(price_val).strip() in ("", "0"):
        formatted_price = "harga tidak tersedia"
    else:
        formatted_price = format_rupiah_num(price_val)

    return f"{model} : {formatted_price}"

def query_pricelist_tool(query: str, tier: str = "ADP") -> str:
    """Fungsi pembantu yang dipanggil oleh Gemini Agent atau command bot.
    Mendukung pencarian 1 tipe maupun sekaligus banyak tipe.
    Format ringkas: Model dan Harga saja.
    """
    # Deteksi apakah query berisi banyak tipe (dipisah newline, koma, semicolon, atau 'dan')
    cleaned = query.replace(";", "\n").replace(",", "\n")
    cleaned = re.sub(r'\s+(?:dan|&)\s+', '\n', cleaned, flags=re.IGNORECASE)
    parts = [p.strip() for p in cleaned.split("\n") if p.strip()]
    
    if len(parts) > 1:
        results = []
        for part in parts:
            p_clean = re.sub(r'^(?:tolong\s+)?(?:carikan\s+)?(?:harga\s+)?(?:adp\s+)?(?:md\s+)?(?:dpp\s+)?(?:untuk\s+)?', '', part, flags=re.IGNORECASE).strip()
            p_clean = re.sub(r'\s+(?:berapa|dong|ya|unit|pcs)$', '', p_clean, flags=re.IGNORECASE).strip()
            if not p_clean:
                continue
            res = search_pricelist(p_clean, tier)
            st = res.get("status")
            if st == "exact":
                results.append(format_single_product_answer(res["product"], tier))
            elif st == "ambiguous":
                m_list = [format_single_product_answer(m, tier) for m in res['matches'][:5]]
                results.append("\n".join(m_list))
            elif st == "not_found_with_suggestions" and res.get("suggestions"):
                sugs = [f"• {s}" for s in res["suggestions"]]
                results.append(f"Model {p_clean} tidak ada di pricelist. Mungkin yang mirip:\n" + "\n".join(sugs))
            else:
                results.append(f"Model {p_clean} tidak ada di pricelist.")
        return "\n".join(results)
    
    # 1 tipe saja
    result = search_pricelist(query, tier)
    st = result.get("status")
    
    if st == "exact":
        return format_single_product_answer(result["product"], result.get("price_tier", "ADP"))
        
    elif st == "ambiguous":
        items = result["matches"]
        lines = [format_single_product_answer(p, tier) for p in items[:6]]
        return "\n".join(lines)
        
    elif st == "not_found_with_suggestions":
        sug = result.get("suggestions", [])
        if sug:
            sugs = [f"• {s}" for s in sug]
            return f"Model {query} tidak ada di pricelist. Mungkin yang mirip:\n" + "\n".join(sugs)
        return f"Model {query} tidak ada di pricelist."
        
    else:
        return f"Model {query} tidak ada di pricelist."

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
    """Membaca file Excel (.xlsx) semua sheet dan menggabungkan (merge) ke data/pricelist.csv tanpa menghapus data produk yang sudah ada."""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(doc_bytes), data_only=True)
        new_extracted = {}

        for sname in wb.sheetnames:
            if sname.lower() in ["update", "history", "changelog", "hot model list for retail", "hot model list for smb project"]:
                continue
            ws = wb[sname]
            rows = list(ws.iter_rows(values_only=True))
            if not rows or len(rows) < 2:
                continue

            header_idx = -1
            for idx, r in enumerate(rows[:12]):
                r_str = [str(cell or "").lower().strip() for cell in r]
                if any("model" in c or "tipe" in c or "type" in c or (c == "name" and any("price" in x or "dpp" in x for x in r_str)) for c in r_str):
                    header_idx = idx
                    break

            if header_idx == -1:
                continue

            header_row = [str(cell or "").lower().strip() for cell in rows[header_idx]]

            col_order = -1
            col_model = -1
            col_desc = -1
            col_dpp = -1
            col_adp = -1
            col_md = -1
            col_msrp = -1
            col_warranty = -1

            for i, col_name in enumerate(header_row):
                if "order" in col_name and ("model" in col_name or "name" in col_name):
                    col_order = i
                elif ("model" in col_name or "tipe" in col_name or "type" in col_name or col_name == "name") and col_model == -1:
                    col_model = i
                elif "desc" in col_name or "keterangan" in col_name or "deskripsi" in col_name or "spesifikasi" in col_name:
                    col_desc = i
                elif "dpp" in col_name:
                    col_dpp = i
                elif "adp" in col_name:
                    col_adp = i
                elif "bottom" in col_name or "md" in col_name or "dealer" in col_name:
                    col_md = i
                elif "msrp" in col_name or "srp" in col_name or "retail" in col_name:
                    col_msrp = i
                elif "warranty" in col_name or "garansi" in col_name:
                    col_warranty = i

            # Fallback untuk kolom harga jika belum ketemu
            if col_dpp == -1 and col_adp == -1 and col_md == -1:
                for i, col_name in enumerate(header_row):
                    if "price" in col_name or "harga" in col_name:
                        col_dpp = i
                        break

            def clean_num(val):
                if not val:
                    return "0"
                try:
                    if isinstance(val, (int, float)):
                        return str(int(round(val)))
                except Exception:
                    pass
                c = re.sub(r'[^0-9]', '', str(val))
                return c if c else "0"

            for r in rows[header_idx + 1:]:
                if not r:
                    continue

                raw_order = str(r[col_order]).strip() if col_order != -1 and len(r) > col_order and r[col_order] else ""
                raw_model = str(r[col_model]).strip() if col_model != -1 and len(r) > col_model and r[col_model] else ""

                candidates = []
                for rm in [raw_order, raw_model]:
                    if not rm or rm.lower() in ("none", "model", "tipe", "type", "order model", "basic model", "name"):
                        continue
                    cm = re.sub(r'[\（\(](?:hot\s*sku|project|new)[^\）\)]*[\）\)]', '', rm, flags=re.IGNORECASE).strip()
                    cm = cm.split('\n')[0].strip()
                    if len(cm) >= 3 and cm not in candidates:
                        candidates.append(cm)

                if not candidates:
                    continue

                # Ambil harga
                p_dpp = clean_num(r[col_dpp]) if col_dpp != -1 and len(r) > col_dpp else "0"
                p_adp = clean_num(r[col_adp]) if col_adp != -1 and len(r) > col_adp else p_dpp
                p_md = clean_num(r[col_md]) if col_md != -1 and len(r) > col_md else (p_dpp or p_adp)
                p_final = p_dpp if int(p_dpp) > 0 else (p_adp if int(p_adp) > 0 else p_md)

                if not p_final or int(p_final) == 0:
                    continue

                desc = str(r[col_desc]).strip() if col_desc != -1 and len(r) > col_desc and r[col_desc] else ""
                desc = desc.replace('\n', ' ')
                msrp = clean_num(r[col_msrp]) if col_msrp != -1 and len(r) > col_msrp else p_final
                warranty = str(r[col_warranty]).strip() if col_warranty != -1 and len(r) > col_warranty and r[col_warranty] else "2 Years Warranty"

                # Deteksi Brand otomatis
                brand = "General"
                first_cand = candidates[0].upper()
                file_str = str(file_path).lower()
                if "hilook" in file_str or first_cand.startswith("THC-") or first_cand.startswith("IPC-B12") or first_cand.startswith("IPC-D12") or first_cand.startswith("IPC-B14") or first_cand.startswith("IPC-D14") or first_cand.startswith("DVR-2") or first_cand.startswith("NVR-1"):
                    brand = "HiLook"
                elif "hiview" in file_str or first_cand.startswith("HV-") or first_cand.startswith("TH-") or first_cand.startswith("T1A20") or first_cand.startswith("B1A20") or first_cand.startswith("T1290") or first_cand.startswith("B1290"):
                    brand = "Hiview"
                elif first_cand.startswith("DS-") or first_cand.startswith("IDS-") or first_cand.startswith("HC-"):
                    brand = "Hikvision"
                elif first_cand.startswith("DH-") or first_cand.startswith("DHI-") or first_cand.startswith("XVR") or first_cand.startswith("NVR") or first_cand.startswith("HAC"):
                    brand = "Dahua"
                elif first_cand.startswith("RG-") or first_cand.startswith("REYEE") or "RUIJIE" in first_cand:
                    brand = "Ruijie"

                for cand in candidates:
                    new_extracted[cand] = {
                        "Model": cand,
                        "Description": desc[:150],
                        "Harga_MD": p_final,
                        "Harga_ADP": p_final,
                        "Harga_DPP": p_dpp or p_final,
                        "Harga_MSRP": msrp or p_final,
                        "Harga_Non_DPP": "",
                        "Category": sname,
                        "Sumber": f"{brand} {sname}",
                        "Warranty": warranty,
                        "Brand": brand
                    }

        if not new_extracted:
            return False, "Tidak ada data produk yang berhasil diekstrak dari seluruh sheet.", 0

        # Muat produk yang sudah ada agar tidak terhapus (Merge)
        existing = {}
        if PRICELIST_PATH.exists():
            with open(PRICELIST_PATH, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    m = r.get("Model", "").strip()
                    if m:
                        existing[m] = r

        # Gabungkan
        for m, item in new_extracted.items():
            existing[m] = item

        fieldnames = ["Model", "Description", "Harga_MD", "Harga_ADP", "Harga_DPP", "Harga_MSRP", "Harga_Non_DPP", "Category", "Sumber", "Warranty", "Brand"]
        with open(PRICELIST_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in existing.values():
                writer.writerow({k: r.get(k, "") for k in fieldnames})

        return True, f"Berhasil mengimpor {len(new_extracted)} produk ke database (Total sekarang: {len(existing)} produk).", len(new_extracted)
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
