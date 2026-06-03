"""
B.A.R.B.A.R.O.S — Local RAG (Retrieval-Augmented Generation)
Kullanıcının bilgisayarındaki dokümanlardan bilgi çekip soru cevaplayabilen sistem.

Desteklenen formatlar: .txt, .md, .pdf, .docx
Embedding: Gemini text-embedding-004
Vektör DB: FAISS (lokal, dosya tabanlı)
"""

import json
import os
import hashlib
import math
import traceback
from pathlib import Path
from typing import Optional

import numpy as np

# Lazy importlar — sadece kullanıldığında yüklenir
_faiss = None
_PyPDF2 = None
_docx = None

def _get_faiss():
    global _faiss
    if _faiss is None:
        import faiss
        _faiss = faiss
    return _faiss

def _get_pypdf2():
    global _PyPDF2
    if _PyPDF2 is None:
        import PyPDF2
        _PyPDF2 = PyPDF2
    return _PyPDF2

def _get_docx():
    global _docx
    if _docx is None:
        import docx
        _docx = docx
    return _docx


# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
RAG_DIR = BASE_DIR / "memory" / "rag_index"
FAISS_INDEX_PATH = RAG_DIR / "index.faiss"
METADATA_PATH = RAG_DIR / "metadata.json"

# ── Config ───────────────────────────────────────────────────────────────────
EMBEDDING_MODEL = "models/text-embedding-004"
EMBEDDING_DIM = 768          # text-embedding-004 çıktı boyutu
CHUNK_SIZE = 500             # Karakter bazlı chunk boyutu
CHUNK_OVERLAP = 100          # Chunk'lar arası örtüşme
SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}

# ── Gemini Client (lazy singleton) ───────────────────────────────────────────
_client = None

def _get_client():
    """Gemini API client'ını app_config'den alınan API key ile başlatır."""
    global _client
    if _client is None:
        from app_config import get_app_config_value
        from google import genai
        api_key = str(get_app_config_value("gemini_api_key", "") or "")
        if not api_key:
            raise RuntimeError("Gemini API key bulunamadı. RAG çalışamaz.")
        _client = genai.Client(api_key=api_key)
    return _client


# ── Metadata yönetimi ────────────────────────────────────────────────────────

def _load_metadata() -> dict:
    """Kalıcı metadata dosyasını okur."""
    try:
        if METADATA_PATH.exists():
            with open(METADATA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"chunks": [], "sources": {}}


def _save_metadata(meta: dict):
    """Metadata'yı diske yazar."""
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


# ── Doküman Okuyucular ───────────────────────────────────────────────────────

def _read_txt(path: Path) -> str:
    """TXT ve MD dosyalarını okur."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _read_pdf(path: Path) -> str:
    """PDF dosyalarını okur."""
    PyPDF2 = _get_pypdf2()
    text_parts = []
    try:
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
    except Exception as e:
        print(f"[RAG] PDF okuma hatası ({path.name}): {e}")
    return "\n".join(text_parts)


def _read_docx(path: Path) -> str:
    """DOCX dosyalarını okur."""
    docx_mod = _get_docx()
    try:
        doc = docx_mod.Document(str(path))
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
    except Exception as e:
        print(f"[RAG] DOCX okuma hatası ({path.name}): {e}")
        return ""


def _read_file(path: Path) -> str:
    """Dosya uzantısına göre doğru okuyucuyu seçer."""
    ext = path.suffix.lower()
    if ext in (".txt", ".md"):
        return _read_txt(path)
    elif ext == ".pdf":
        return _read_pdf(path)
    elif ext == ".docx":
        return _read_docx(path)
    return ""


# ── Chunking ─────────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Metni örtüşen parçalara böler."""
    if not text or not text.strip():
        return []
    
    # Önce paragraf sınırlarında bölmeyi dene
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk = (current_chunk + "\n\n" + para).strip()
        else:
            if current_chunk:
                chunks.append(current_chunk)
            # Paragraf tek başına chunk_size'dan büyükse, karakter bazlı böl
            if len(para) > chunk_size:
                words = para.split()
                sub_chunk = ""
                for word in words:
                    if len(sub_chunk) + len(word) + 1 <= chunk_size:
                        sub_chunk = (sub_chunk + " " + word).strip()
                    else:
                        if sub_chunk:
                            chunks.append(sub_chunk)
                        sub_chunk = word
                if sub_chunk:
                    current_chunk = sub_chunk
                else:
                    current_chunk = ""
            else:
                current_chunk = para
    
    if current_chunk:
        chunks.append(current_chunk)
    
    # Çok kısa chunk'ları birleştir (min 50 karakter)
    final_chunks = []
    for c in chunks:
        if len(c) < 50 and final_chunks:
            final_chunks[-1] = final_chunks[-1] + "\n\n" + c
        else:
            final_chunks.append(c)
    
    return final_chunks


# ── Embedding ────────────────────────────────────────────────────────────────

def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Gemini Embedding API ile metin listesini vektöre çevirir."""
    client = _get_client()
    all_embeddings = []
    
    # API'yi batch'ler halinde çağır (max 100 per request)
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        try:
            result = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=batch,
            )
            for emb in result.embeddings:
                all_embeddings.append(emb.values)
        except Exception as e:
            print(f"[RAG] Embedding hatası (batch {i}): {e}")
            traceback.print_exc()
            # Hatalı batch'i sıfır vektörle doldur
            for _ in batch:
                all_embeddings.append([0.0] * EMBEDDING_DIM)
    
    return all_embeddings


def _embed_single(text: str) -> list[float]:
    """Tek bir metni vektöre çevirir."""
    result = _embed_texts([text])
    return result[0] if result else [0.0] * EMBEDDING_DIM


# ── FAISS İndeks Yönetimi ────────────────────────────────────────────────────

def _load_or_create_index():
    """FAISS indeksini diskten yükler veya yeni oluşturur."""
    faiss = _get_faiss()
    if FAISS_INDEX_PATH.exists():
        try:
            return faiss.read_index(str(FAISS_INDEX_PATH))
        except Exception as e:
            print(f"[RAG] FAISS indeks okuma hatası: {e}")
    
    # Yeni indeks (cosine similarity için normalize + Inner Product)
    index = faiss.IndexFlatIP(EMBEDDING_DIM)
    return index


def _save_index(index):
    """FAISS indeksini diske yazar."""
    faiss = _get_faiss()
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(FAISS_INDEX_PATH))


# ── Public API ───────────────────────────────────────────────────────────────

def ingest_documents(folder_path: str) -> str:
    """
    Verilen klasörü tarar, desteklenen dosyaları okur, chunk'lar,
    embedding yapar ve FAISS indeksine ekler.
    
    Returns: İşlem sonucu mesajı
    """
    folder = Path(folder_path).expanduser().resolve()
    
    if not folder.exists():
        return f"Hata: '{folder_path}' klasörü bulunamadı."
    if not folder.is_dir():
        return f"Hata: '{folder_path}' bir klasör değil."
    
    # Desteklenen dosyaları bul
    files_found = []
    for ext in SUPPORTED_EXTENSIONS:
        files_found.extend(folder.rglob(f"*{ext}"))
    
    if not files_found:
        return f"'{folder_path}' klasöründe desteklenen dosya bulunamadı (.txt, .md, .pdf, .docx)."
    
    meta = _load_metadata()
    index = _load_or_create_index()
    
    total_chunks = 0
    processed_files = 0
    skipped_files = 0
    
    all_new_chunks = []
    all_new_meta = []
    
    for file_path in sorted(files_found):
        # Dosya hash'i ile tekrar yüklemeyi önle
        file_hash = hashlib.md5(str(file_path).encode() + str(file_path.stat().st_mtime).encode()).hexdigest()
        
        if file_hash in meta.get("sources", {}):
            skipped_files += 1
            continue
        
        print(f"[RAG] İşleniyor: {file_path.name}")
        
        text = _read_file(file_path)
        if not text or len(text.strip()) < 20:
            print(f"[RAG] Atlandı (boş veya çok kısa): {file_path.name}")
            continue
        
        chunks = _chunk_text(text)
        if not chunks:
            continue
        
        for chunk_idx, chunk_text in enumerate(chunks):
            all_new_chunks.append(chunk_text)
            all_new_meta.append({
                "source_file": str(file_path),
                "file_name": file_path.name,
                "chunk_index": chunk_idx,
                "total_chunks": len(chunks),
                "file_hash": file_hash,
                "char_count": len(chunk_text),
            })
        
        meta.setdefault("sources", {})[file_hash] = {
            "path": str(file_path),
            "name": file_path.name,
            "chunks": len(chunks),
        }
        
        total_chunks += len(chunks)
        processed_files += 1
    
    if not all_new_chunks:
        if skipped_files > 0:
            return f"Bu klasördeki {skipped_files} dosya zaten yüklenmiş. Yeni dosya bulunamadı."
        return "İşlenecek içerik bulunamadı."
    
    # Toplu embedding
    print(f"[RAG] {len(all_new_chunks)} chunk için embedding hesaplanıyor...")
    embeddings = _embed_texts(all_new_chunks)
    
    # Normalize et (cosine similarity için)
    faiss = _get_faiss()
    emb_array = np.array(embeddings, dtype=np.float32)
    faiss.normalize_L2(emb_array)
    
    # FAISS'e ekle
    index.add(emb_array)
    
    # Metadata'yı güncelle
    meta.setdefault("chunks", []).extend(all_new_meta)
    
    # Kaydet
    _save_index(index)
    _save_metadata(meta)
    
    result_lines = [
        f"✅ {processed_files} dosya başarıyla işlendi.",
        f"📄 Toplam {total_chunks} parça indekslendi.",
    ]
    if skipped_files > 0:
        result_lines.append(f"⏭️ {skipped_files} dosya zaten yüklü olduğu için atlandı.")
    result_lines.append(f"📁 İndeks konumu: {RAG_DIR}")
    
    return "\n".join(result_lines)


def query_documents(question: str, top_k: int = 5) -> str:
    """
    Soruyu embedding'e çevirir, FAISS'ten en alakalı chunk'ları bulur
    ve kaynak bilgileriyle birlikte döndürür.
    
    Returns: Bağlam metni (Gemini'ye gönderilecek)
    """
    meta = _load_metadata()
    chunks_meta = meta.get("chunks", [])
    
    if not chunks_meta:
        return "RAG indeksinde henüz doküman yok. Önce 'rag_ingest' ile bir klasör yükle."
    
    if not FAISS_INDEX_PATH.exists():
        return "FAISS indeks dosyası bulunamadı. Önce dokümanları yükle."
    
    index = _load_or_create_index()
    if index.ntotal == 0:
        return "İndeks boş. Önce dokümanları yükle."
    
    # Soruyu embedding'e çevir
    q_emb = _embed_single(question)
    q_array = np.array([q_emb], dtype=np.float32)
    
    faiss = _get_faiss()
    faiss.normalize_L2(q_array)
    
    # En yakın k sonucu bul
    k = min(top_k, index.ntotal)
    distances, indices = index.search(q_array, k)
    
    # Sonuçları formatla
    results = []
    seen_files = set()
    
    for rank, (dist, idx) in enumerate(zip(distances[0], indices[0]), 1):
        if idx < 0 or idx >= len(chunks_meta):
            continue
        
        chunk_info = chunks_meta[idx]
        file_name = chunk_info.get("file_name", "bilinmiyor")
        chunk_idx = chunk_info.get("chunk_index", 0)
        total = chunk_info.get("total_chunks", 1)
        score = float(dist)
        
        # Çok düşük skor olanları dahil etme (eşik: 0.3)
        if score < 0.3:
            continue
        
        # Chunk metnini oku (metadata'dan source_file üzerinden)
        source_file = Path(chunk_info.get("source_file", ""))
        chunk_text = _get_chunk_text(source_file, chunk_idx)
        
        if chunk_text:
            seen_files.add(file_name)
            results.append(
                f"[Kaynak: {file_name} | Parça {chunk_idx+1}/{total} | Skor: {score:.2f}]\n{chunk_text}"
            )
    
    if not results:
        return "Dokümanlarında bu soruyla ilgili anlamlı bir eşleşme bulunamadı."
    
    header = f"📚 {len(results)} alakalı parça bulundu ({len(seen_files)} dosyadan):\n"
    separator = "\n" + "─" * 60 + "\n"
    
    return header + separator.join(results)


def _get_chunk_text(source_file: Path, chunk_index: int) -> Optional[str]:
    """Kaynak dosyadan ilgili chunk'ı yeniden okur."""
    try:
        if not source_file.exists():
            return "[Dosya artık mevcut değil]"
        text = _read_file(source_file)
        chunks = _chunk_text(text)
        if chunk_index < len(chunks):
            return chunks[chunk_index]
        return "[Chunk bulunamadı — dosya değişmiş olabilir]"
    except Exception as e:
        return f"[Okuma hatası: {e}]"


def list_indexed_sources() -> str:
    """İndekste bulunan dosyaları listeler."""
    meta = _load_metadata()
    sources = meta.get("sources", {})
    
    if not sources:
        return "RAG indeksinde henüz hiç doküman yok."
    
    lines = [f"📁 RAG İndeksinde {len(sources)} dosya var:\n"]
    total_chunks = 0
    
    for file_hash, info in sources.items():
        name = info.get("name", "bilinmiyor")
        path = info.get("path", "")
        chunks = info.get("chunks", 0)
        total_chunks += chunks
        lines.append(f"  • {name} ({chunks} parça) — {path}")
    
    lines.append(f"\n📊 Toplam: {total_chunks} parça indekslenmiş.")
    return "\n".join(lines)


def clear_index() -> str:
    """Tüm RAG indeksini siler."""
    try:
        if FAISS_INDEX_PATH.exists():
            FAISS_INDEX_PATH.unlink()
        if METADATA_PATH.exists():
            METADATA_PATH.unlink()
        return "✅ RAG indeksi tamamen temizlendi."
    except Exception as e:
        return f"Hata: İndeks temizlenemedi — {e}"
