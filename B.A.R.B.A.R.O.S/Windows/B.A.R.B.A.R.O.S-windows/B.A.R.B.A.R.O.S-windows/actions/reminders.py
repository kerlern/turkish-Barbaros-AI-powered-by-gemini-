"""
Hatırlatıcılar — Windows sürümü.

Windows üzerinde yerel JSON tabanlı anımsatıcı sistemi.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REMINDERS_FILE = DATA_DIR / "reminders.json"

def _ensure_reminders_file() -> None:
    if not DATA_DIR.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not REMINDERS_FILE.exists():
        with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

def _load_reminders() -> list[dict]:
    _ensure_reminders_file()
    try:
        with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_reminders(reminders: list[dict]) -> None:
    _ensure_reminders_file()
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(reminders, f, indent=4, ensure_ascii=False)

def get_reminders(query: str = "upcoming", limit: int = 8, list_name: str = "") -> str:
    reminders = _load_reminders()
    if not reminders:
        return "Şu anda hiç aktif anımsatıcı yok."
    
    # notify edilmemiş olanları getir
    active_reminders = [r for r in reminders if not r.get("notified", False)]
    
    if not active_reminders:
        return "Tüm anımsatıcıların süresi doldu ve bildirimleri yapıldı."
        
    # Zamana göre sırala (due_iso'su olmayanları en sona at)
    def sort_key(r):
        iso = r.get("due_iso", "")
        if not iso:
            return "9999-12-31T23:59:59"
        return iso

    active_reminders.sort(key=sort_key)
    
    lines = []
    for r in active_reminders[:limit]:
        title = r.get("title", "İsimsiz")
        due = r.get("due_iso", "")
        if due:
            try:
                dt = datetime.fromisoformat(due.replace('Z', '+00:00'))
                due_str = dt.strftime("%d %b %Y %H:%M")
            except Exception:
                due_str = due
            lines.append(f"- {title} (Zaman: {due_str})")
        else:
            lines.append(f"- {title}")
            
    return "Mevcut anımsatıcılar:\n" + "\n".join(lines)


def add_reminder(
    title: str,
    due_iso: str = "",
    notes: str = "",
    list_name: str = "",
    priority: str = "",
    all_day: bool = False,
) -> str:
    reminders = _load_reminders()
    
    reminder_id = str(uuid.uuid4())
    reminder = {
        "id": reminder_id,
        "title": title,
        "due_iso": due_iso,
        "notes": notes,
        "list_name": list_name,
        "priority": priority,
        "all_day": all_day,
        "notified": False,
        "created_at": datetime.now().isoformat()
    }
    
    reminders.append(reminder)
    _save_reminders(reminders)
    
    due_str = ""
    if due_iso:
        try:
            dt = datetime.fromisoformat(due_iso.replace('Z', '+00:00'))
            due_str = f" ({dt.strftime('%d %b %H:%M')} için)"
        except Exception:
            due_str = f" ({due_iso} için)"
            
    return f"'{title}' başlıklı anımsatıcı başarıyla kaydedildi{due_str}. Zamanı geldiğinde bildirim göndereceğim."

def mark_reminder_notified(reminder_id: str) -> None:
    reminders = _load_reminders()
    for r in reminders:
        if r.get("id") == reminder_id:
            r["notified"] = True
            break
    _save_reminders(reminders)
