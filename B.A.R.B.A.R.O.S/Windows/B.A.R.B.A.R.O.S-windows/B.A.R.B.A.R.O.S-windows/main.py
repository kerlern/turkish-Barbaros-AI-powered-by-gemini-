#!/usr/bin/env python3
"""
B.A.R.B.A.R.O.S Windows — Gercek zamanli sesli yardimci cekirdegi
KERLERN tarafından yapılmıştır — Hikmet
Windows ortamina uyarlanmis calisma akisi
"""

import asyncio
import datetime
import threading
import traceback
import os
import re
from pathlib import Path

import pyaudio  # type: ignore[reportMissingModuleSource]
from google import genai  # type: ignore[reportMissingImports]
from google.genai import types  # type: ignore[reportMissingImports]

from app_config import get_app_config_value
from ui import JarvisUI
from memory.memory_manager import load_memory, update_memory, delete_memory, format_memory_for_prompt
from actions.open_app import open_app
from actions.sys_info  import sys_info
from actions.calendar import get_calendar_events, add_calendar_event, delete_calendar_event
from actions.reminders import get_reminders, add_reminder
from actions.browser   import browser_control
from actions.shell     import system_action
from actions.whatsapp  import send_whatsapp_message, save_whatsapp_contact
from actions.media     import play_media
from actions.weather   import get_weather_summary
from actions.screen_vision import analyze_screen
from actions.youtube_stats import get_youtube_channel_report
from actions.local_rag import ingest_documents, query_documents, list_indexed_sources, clear_index as rag_clear_index
from wakeup_listener import WakeGestureListener

try:
    from win11toast import toast
except ImportError:
    toast = None

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).resolve().parent
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"


CONTROL_TOKEN_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

# ── Model ───────────────────────────────────────────────────────────────────
LIVE_MODEL = "models/gemini-2.5-flash-native-audio-latest"

# ── Audio ───────────────────────────────────────────────────────────────────
FORMAT           = pyaudio.paInt16
CHANNELS         = 1
SEND_SAMPLE_RATE = 16000
RECV_SAMPLE_RATE = 24000
CHUNK_SIZE       = 1024

# ── Bağlantı kararlılığı sabitleri ──────────────────────────────────────────
KEEPALIVE_INTERVAL   = 8    # saniye — session timeout'u önlemek için keepalive aralığı (düşük = daha kararlı)
RECONNECT_BASE_DELAY = 3    # saniye — yeniden bağlanma başlangıç gecikmesi
RECONNECT_MAX_DELAY  = 45   # saniye — yeniden bağlanma maksimum gecikmesi
SEND_TIMEOUT         = 12   # saniye — ses chunk gönderim timeout'u
KEEPALIVE_FAIL_THRESHOLD = 5  # keepalive fail sayısı (kaç timeout sonra bağlantı kopmuş sayılır)

pya              = pyaudio.PyAudio()

# ── Tool tanımları ──────────────────────────────────────────────────────────
TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": "Windows'ta herhangi bir uygulamayı açar. Spotify, Chrome, Terminal, Dosya Gezgini, VS Code vb.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Uygulama adı (örn. 'Spotify', 'Chrome', 'Terminal')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "sys_info",
        "description": "Sistem bilgisi alır: pil durumu, CPU, RAM, disk, saat, tarih, ağ bağlantısı.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "battery | cpu | ram | disk | time | date | network | all"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_weather",
        "description": (
            "Anlik hava durumunu ozetler. Varsayilan konum Istanbul'dur. "
            "Kullanici hava durumunu, sicakligi veya yagmur durumunu sordugunda kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "location": {
                    "type": "STRING",
                    "description": "Sehir veya konum. Bos birakilirsa Istanbul kullanilir."
                }
            }
        }
    },
    {
        "name": "get_calendar_events",
        "description": (
            "Takvim (Google Calendar) etkinliklerini okur. "
            "Bugun, yarin, siradaki etkinlik veya yaklasan ajandayi ozetler. "
            "Kullanici toplanti, takvim, ajanda, etkinlik veya gunluk programini sordugunda kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": (
                        "today | tomorrow | next | agenda | week veya dogal dilde "
                        "'onumuzdeki 30 gun', '2 hafta', 'bu ay', 'gelecek ay'"
                    )
                },
                "limit": {
                    "type": "NUMBER",
                    "description": "Maksimum etkinlik sayisi"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "add_calendar_event",
        "description": (
            "Takvim (Google Calendar) servisine yeni etkinlik ekler. "
            "Kullanici toplanti, randevu, takvime ekleme veya etkinlik olusturma isterse kullan. "
            "Baslangic tarihini gercek tarih/saat olarak ver; bitis verilmezse varsayilan sure kullanilir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Etkinlik basligi. Ornek: 'Disci Randevusu'"
                },
                "start_iso": {
                    "type": "STRING",
                    "description": "Baslangic tarih/saat. ISO veya yyyy-MM-dd HH:mm formatinda."
                },
                "end_iso": {
                    "type": "STRING",
                    "description": "Bitis tarih/saat. Opsiyonel."
                },
                "location": {
                    "type": "STRING",
                    "description": "Etkinlik konumu. Opsiyonel."
                },
                "notes": {
                    "type": "STRING",
                    "description": "Etkinlik notlari. Opsiyonel."
                },
                "calendar_name": {
                    "type": "STRING",
                    "description": "Eklenecek takvim adi. Opsiyonel."
                },
                "all_day": {
                    "type": "BOOLEAN",
                    "description": "true ise tum gun etkinligi olusturur."
                }
            },
            "required": ["title", "start_iso"]
        }
    },
    {
        "name": "delete_calendar_event",
        "description": (
            "Takvim (Google Calendar) servisinden etkinlik siler. "
            "Kullanici bir toplantiyi, randevuyu veya takvim kaydini silmek istediginde kullan. "
            "Ayni ada birden fazla etkinlik varsa dogru kaydi bulmak icin baslangic tarihini gercek tarih/saat olarak ver."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Silinecek etkinlik basligi. Ornek: 'Disci Randevusu'"
                },
                "start_iso": {
                    "type": "STRING",
                    "description": "Opsiyonel tarih/saat. Ayni isimli birden fazla etkinligi ayirt etmek icin kullan."
                },
                "calendar_name": {
                    "type": "STRING",
                    "description": "Opsiyonel takvim adi"
                },
                "delete_all_matches": {
                    "type": "BOOLEAN",
                    "description": "true ise eslesen tum etkinlikleri siler"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "get_reminders",
        "description": (
            "Hatırlatıcılar (Microsoft To-Do) listesini okur. "
            "Bugunku, yaklasan, geciken veya tum acik animsaticilari ozetler. "
            "Kullanici hatirlatma, animsatici, reminder veya yapilacaklar listesini sordugunda kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "today | upcoming | overdue | all | next"
                },
                "limit": {
                    "type": "NUMBER",
                    "description": "Maksimum animsatici sayisi"
                },
                "list_name": {
                    "type": "STRING",
                    "description": "Istenirse belirli bir animsatici listesi adi"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "add_reminder",
        "description": (
            "Hatırlatıcılar (Microsoft To-Do) uygulamasina yeni bir animsatici ekler. "
            "Kullanici 'hatirlat', 'animsatici ekle', 'reminder kur' dediginde kullan. "
            "Goreli zaman ifadelerini bugunku tarih baglamina gore due_iso alanina ISO formatinda cevir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Animsatici basligi"
                },
                "due_iso": {
                    "type": "STRING",
                    "description": "Opsiyonel tarih/saat. Ornek: 2026-04-13T09:00 veya tum gun icin 2026-04-13"
                },
                "notes": {
                    "type": "STRING",
                    "description": "Opsiyonel not"
                },
                "list_name": {
                    "type": "STRING",
                    "description": "Opsiyonel animsatici listesi"
                },
                "priority": {
                    "type": "STRING",
                    "description": "low | medium | high"
                },
                "all_day": {
                    "type": "BOOLEAN",
                    "description": "Tum gun animsatici ise true"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "browser_control",
        "description": "Tarayıcıda URL açar, Google'da arama yapar veya YouTube'da ilk sonucu doğrudan oynatır.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "open_url | search | play_youtube"},
                "url":    {"type": "STRING", "description": "Açılacak URL (open_url için)"},
                "query":  {"type": "STRING", "description": "Arama sorgusu (search veya play_youtube için)"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "system_action",
        "description": "Güvenli sistem ve dosya işlemleri yapar. (dir, copy, tasklist vb.)",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": { "type": "STRING", "description": "list_dir | make_dir | read_file | copy | move | delete | list_tasks | ping" },
                "target": { "type": "STRING", "description": "Hedef dosya yolu, klasör, görev adı veya IP adresi" },
                "destination": { "type": "STRING", "description": "Kopyalama/Taşıma için varış klasörü/dosyası" }
            },
            "required": ["action"]
        }
    },
    {
        "name": "play_media",
        "description": (
            "YouTube, Spotify veya Spotify/YouTube'da şarkı, müzik veya video açar. "
            "Kullanıcı belirli bir platform söylerse onu kullan. "
            "Belirtmezse uygun olanı dene. "
            "Kullanıcı 'çal', 'oynat', 'aç' diyorsa autoplay=true kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Şarkı, sanatçı, albüm veya video arama ifadesi"
                },
                "provider": {
                    "type": "STRING",
                    "description": "auto | youtube | spotify | apple_music"
                },
                "autoplay": {
                    "type": "BOOLEAN",
                    "description": "true ise mümkünse doğrudan oynatır"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_youtube_channel_report",
        "description": (
            "YouTube kanalinin public istatistiklerini ve son videolarin performansini raporlar. "
            "Kullanici kanal istatistiklerini, abone sayisini, son videolarini, buyume hizini "
            "veya YouTube analizini sordugunda kullan. Bu arac Studio yerine public YouTube Data API verisini kullanir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": (
                        "Dogal dilde analiz istegi. Ornek: "
                        "'YouTube istatistiklerim nasil', 'son videolarimi analiz et', "
                        "'kanal buyumemi ozetle'"
                    )
                },
                "handle": {
                    "type": "STRING",
                    "description": (
                        "Opsiyonel kanal handle'i, kanal linki veya kanal ID'si. "
                        "Bos birakilirsa ayarlardaki youtube_channel_handle kullanilir."
                    )
                },
                "video_limit": {
                    "type": "NUMBER",
                    "description": "Analize dahil edilecek son video sayisi. Varsayilan 6."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "analyze_screen",
        "description": (
            "Aktif pencerenin ekran goruntusunu alip Gemini vision ile analiz eder. "
            "Kullanici ekranda ne oldugunu, bir hatayi, gorunen metni, butonlari veya pencere icerigini sordugunda kullan. "
            "Bu surum yalnizca aktif pencereyi destekler."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Kullanicinin ekranla ilgili sorusu. Ornek: 'Bu hatayi oku', 'Ekranda ne var?'"
                },
                "target": {
                    "type": "STRING",
                    "description": "Su an sadece active_window desteklenir."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "save_memory",
        "description": "Kullanıcı hakkında önemli bilgiyi kalıcı belleğe kaydeder. İsim, tercihler, projeler vb. duyunca sessizce çağır.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": "identity | preferences | projects | notes"
                },
                "key":   {"type": "STRING", "description": "Kısa anahtar (örn. 'name')"},
                "value": {"type": "STRING", "description": "Değer (İngilizce)"}
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "delete_memory",
        "description": (
            "Kalici hafizadaki bir kaydi siler. "
            "Kullanici 'bunu hafizandan kaldir', 'unut', 'sil' gibi bir sey derse kullan. "
            "Mumkunse category ve key ile sil; emin degilsen match_text ile ilgili kaydi bulup kaldir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": "Kaydin kategorisi. Ornek: notes | identity | preferences | projects"
                },
                "key": {
                    "type": "STRING",
                    "description": "Silinecek anahtar. Ornek: claude_limit_refresh"
                },
                "match_text": {
                    "type": "STRING",
                    "description": "Kaydi bulmak icin kullanilacak dogal dil parcasi. Ornek: 'claude ai limit yenilenmesi'"
                }
            }
        }
    },
    {
        "name": "send_whatsapp_message",
        "description": (
            "WhatsApp Desktop veya WhatsApp Web üzerinden mesaj taslağı açar veya mesajı gönderir. "
            "Kişi adı veya telefon numarasıyla çalışabilir. "
            "Telefon numarası verilmemişse kişi adını önce kayıtlı WhatsApp kişileri ve içe aktarılan telefon rehberinde ara. "
            "Kullanıcı 'gönder', 'yolla', 'ile', 'hemen gönder' gibi açık bir gönderme niyeti söylüyorsa "
            "ekstra onay istemeden send_now=true kullan. "
            "Yalnızca 'hazırla', 'taslak aç', 'yaz ama gönderme' diyorsa send_now=false kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "recipient_name": {
                    "type": "STRING",
                    "description": "Kişi adı. Örn: 'Anne', 'Ahmet', 'Ece'"
                },
                "phone_number": {
                    "type": "STRING",
                    "description": "Uluslararası telefon numarası. Örn: +905551112233"
                },
                "message": {
                    "type": "STRING",
                    "description": "Gönderilecek mesaj içeriği"
                },
                "app_target": {
                    "type": "STRING",
                    "description": "desktop | web | auto. Varsayılan auto, tercihen desktop."
                },
                "send_now": {
                    "type": "BOOLEAN",
                    "description": "true ise sohbet açıldıktan sonra mesajı otomatik gönderir"
                }
            },
            "required": ["message"]
        }
    },
    {
        "name": "save_whatsapp_contact",
        "description": (
            "Sık kullanılan bir WhatsApp kişisini adı ve telefon numarasıyla kalıcı belleğe kaydeder. "
            "Kullanıcı bir kişiyi 'annem', 'Ahmet', 'iş ortağım' gibi tekrar kullanılacak şekilde tanımladığında kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "display_name": {
                    "type": "STRING",
                    "description": "Kaydedilecek kişi adı. Örn: 'Annem', 'Ahmet'"
                },
                "phone_number": {
                    "type": "STRING",
                    "description": "Uluslararası telefon numarası. Örn: +905551112233"
                },
                "aliases": {
                    "type": "STRING",
                    "description": "Virgülle ayrılmış alternatif hitaplar. Örn: 'anne, annem, mom'"
                }
            },
            "required": ["display_name", "phone_number"]
        }
    },
    {
        "name": "rag_ingest",
        "description": (
            "Kullanıcının bilgisayarındaki bir klasördeki dokümanları (txt, md, pdf, docx) tarar, "
            "parçalara böler ve lokal RAG indeksine yükler. "
            "Kullanıcı 'şu klasördeki dokümanları yükle', 'notlarımı indeksle', "
            "'dosyalarımı RAG'a ekle' dediğinde kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "folder_path": {
                    "type": "STRING",
                    "description": "Taranacak klasör yolu. Örn: 'C:/Users/kullanici/Documents/notlar' veya '~/Desktop/projeler'"
                }
            },
            "required": ["folder_path"]
        }
    },
    {
        "name": "rag_query",
        "description": (
            "Daha önce RAG indeksine yüklenmiş dokümanlardan soru sorar. "
            "Soruyla en alakalı parçaları bulur ve kaynak bilgileriyle birlikte döndürür. "
            "Kullanıcı 'dokümanlarımda X hakkında ne yazıyor?', 'notlarımda Y var mı?', "
            "'yüklediğim dosyalarda Z ile ilgili bilgi bul' dediğinde kullan. "
            "Yanıtı oluştururken döndürülen bağlamı kullanarak doğal ve özetleyici bir cevap ver."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "question": {
                    "type": "STRING",
                    "description": "Dokümanlarda aranacak soru veya konu"
                },
                "top_k": {
                    "type": "NUMBER",
                    "description": "Döndürülecek en alakalı parça sayısı. Varsayılan 5."
                }
            },
            "required": ["question"]
        }
    },
    {
        "name": "rag_list_sources",
        "description": (
            "RAG indeksinde hangi dosyaların yüklü olduğunu listeler. "
            "Kullanıcı 'hangi dokümanlar yüklü?', 'RAG indeksimde ne var?' dediğinde kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "rag_clear",
        "description": (
            "RAG indeksini tamamen siler ve sıfırlar. "
            "Kullanıcı 'RAG indeksini temizle', 'yüklenen dokümanları sil' dediğinde kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    }
]


def get_api_key() -> str:
    return str(get_app_config_value("gemini_api_key", "") or "")


def load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "Sen B.A.R.B.A.R.O.S'sin — Windows'ta çalışan kişisel AI asistanı. "
            "Türkçe konuş. Kısa ve net yanıtlar ver. "
            "Araçları kullanarak görevleri tamamla, asla taklit etme."
        )


class JarvisLive:
    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._reconnect_delay = RECONNECT_BASE_DELAY

        self.ui.on_text_command  = self._on_text_command
        self.ui.on_pause_toggle  = self._on_pause_toggle
        self.ui.on_effects_state_change = self._on_effects_state_change
        self._paused             = False

    def _on_pause_toggle(self, paused: bool):
        self._paused = paused

    def _on_effects_state_change(self, enabled: bool):
        pass

    def _focus_ui_section_for_tool(self, tool_name: str, args: dict):
        if tool_name == "sys_info":
            query = str(args.get("query", "")).strip().lower()
            if query in {"time", "saat", "zaman", "date", "tarih"}:
                self.ui.focus_panel("time", duration_ms=5200)
            else:
                self.ui.focus_panel("system", duration_ms=5200)
        elif tool_name == "get_weather":
            self.ui.focus_panel("weather", duration_ms=5600)

    def _on_text_command(self, text: str):
        if self._paused:
            return
        self.ui.write_log(f"Siz: {text}")
        if not self._loop or not self.session:
            self.ui.write_log("ERR: B.A.R.B.A.R.O.S bağlantısı henüz hazır değil.")
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    async def _interrupt_audio(self):
        try:
            if self.audio_in_queue:
                while not self.audio_in_queue.empty():
                    try:
                        self.audio_in_queue.get_nowait()
                    except Exception:
                        break
            if self.session:
                await self.session.send_realtime_input(audio_stream_end=True)
            self.set_speaking(False)
        except Exception:
            pass


    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        else:
            self.ui.set_state("LISTENING")

    def _cleanup_session(self):
        """Bağlantı koptuğunda tüm state'i güvenli şekilde sıfırlar."""
        self.session = None
        if self.audio_in_queue:
            while not self.audio_in_queue.empty():
                try:
                    self.audio_in_queue.get_nowait()
                except Exception:
                    break
        self.audio_in_queue = None
        self.out_queue = None
        self.set_speaking(False)

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.ui.write_debug(f"{tool_name}: {short}", level="ERROR")
        self.ui.set_state("ERROR")

    @staticmethod
    def _result_looks_like_error(result) -> bool:
        text = str(result or "").strip().lower()
        if not text:
            return False
        error_markers = (
            "hata",
            "error",
            "alinamadi",
            "alınamadı",
            "bulunamadi",
            "bulunamadı",
            "acilamadi",
            "açılamadı",
            "tamamlanamadi",
            "tamamlanamadı",
            "gecersiz",
            "geçersiz",
            "izin gerekiyor",
            "izin gerekli",
            "baglanti",
            "bağlantı",
            "gerekli.",
        )
        return any(marker in text for marker in error_markers)

    @staticmethod
    def _should_play_success_sfx(tool_name: str, args: dict, result) -> bool:
        action_tools = {
            "open_app",
            "add_calendar_event",
            "add_reminder",
            "delete_calendar_event",
            "remove_calendar_event",
        }
        if tool_name in action_tools:
            return True

        if tool_name == "send_whatsapp_message":
            text = str(result or "").lower()
            if bool(args.get("send_now", False)):
                return "gönderildi" in text or "gonderildi" in text
            return False

        return False

    @staticmethod
    def _clean_transcript_text(text: str) -> tuple[str, bool]:
        raw = str(text or "")
        had_noise = False
        if CONTROL_TOKEN_RE.search(raw):
            had_noise = True
            raw = CONTROL_TOKEN_RE.sub(" ", raw)
        cleaned = []
        for ch in raw:
            if ch in "\n\r\t" or ord(ch) >= 32:
                cleaned.append(ch)
            else:
                had_noise = True
        normalized = " ".join("".join(cleaned).split())
        return normalized.strip(), had_noise

    def _build_config(self) -> types.LiveConnectConfig:
        memory  = load_memory()
        mem_str = format_memory_for_prompt(memory)
        sys_p   = load_system_prompt()
        now     = datetime.datetime.now()
        time_ctx = f"[ŞU ANKİ ZAMAN]\n{now.strftime('%A, %d %B %Y — %H:%M')}\n\n"

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str + "\n\n")
        parts.append(sys_p)

        # ── Live API Ses ve Yanıt Konfigürasyonu ───────────────────────────────────
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"], # Modelin size sesle yanıt vermesini sağlar
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        # Eğer ayarlardan çekmek istersen: str(get_app_config_value("voice", "Charon") or "Charon")
                        voice_name="Orus" #<── İSTEDİĞİNİZ SESİ BURAYA YAZIN (Örn: Puck, Charon, Kore, Fenrir)
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})
        print(f"[B.A.R.B.A.R.O.S] 🔧 {name} {args}")
        self.ui.set_state("THINKING")

        loop   = asyncio.get_event_loop()
        result = "Tamam."
        had_exception = False

        try:
            if name == "save_memory":
                cat = args.get("category", "notes")
                key = args.get("key", "")
                val = args.get("value", "")
                if key and val:
                    update_memory({cat: {key: {"value": val}}})
                    print(f"[Memory] 💾 {cat}/{key} = {val}")
                result = "ok"

            elif name == "delete_memory":
                result = delete_memory(
                    args.get("category", ""),
                    args.get("key", ""),
                    args.get("match_text", ""),
                )

            elif name == "open_app":
                r = await loop.run_in_executor(
                    None, lambda: open_app(args.get("app_name", "")))
                result = r or f"{args.get('app_name')} açıldı."

            elif name == "sys_info":
                self._focus_ui_section_for_tool(name, args)
                r = await loop.run_in_executor(
                    None, lambda: sys_info(args.get("query", "all")))
                result = r or "Bilgi alındı."

            elif name == "get_weather":
                self._focus_ui_section_for_tool(name, args)
                r = await loop.run_in_executor(
                    None, lambda: get_weather_summary(args.get("location") or None))
                result = r or "Hava durumu bilgisi alindi."

            elif name == "get_calendar_events":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_calendar_events(
                        args.get("query", "today"),
                        int(args.get("limit", 6) or 6),
                    ),
                )
                result = r or "Takvim bilgisi alindi."

            elif name == "add_calendar_event":
                r = await loop.run_in_executor(
                    None,
                    lambda: add_calendar_event(
                        args.get("title", ""),
                        args.get("start_iso", ""),
                        args.get("end_iso", ""),
                        args.get("notes", ""),
                        args.get("location", ""),
                        args.get("calendar_name", ""),
                        bool(args.get("all_day", False)),
                    ),
                )
                result = r or "Takvim etkinligi eklendi."

            elif name == "delete_calendar_event":
                r = await loop.run_in_executor(
                    None,
                    lambda: delete_calendar_event(
                        args.get("title", ""),
                        args.get("start_iso", ""),
                        args.get("calendar_name", ""),
                        bool(args.get("delete_all_matches", False)),
                    ),
                )
                result = r or "Takvim etkinligi silindi."

            elif name == "get_reminders":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_reminders(
                        args.get("query", "upcoming"),
                        int(args.get("limit", 8) or 8),
                        args.get("list_name", ""),
                    ),
                )
                result = r or "Animsatici bilgisi alindi."

            elif name == "add_reminder":
                r = await loop.run_in_executor(
                    None,
                    lambda: add_reminder(
                        args.get("title", ""),
                        args.get("due_iso", ""),
                        args.get("notes", ""),
                        args.get("list_name", ""),
                        args.get("priority", ""),
                        bool(args.get("all_day", False)),
                    ),
                )
                result = r or "Animsatici eklendi."

            elif name == "browser_control":
                r = await loop.run_in_executor(
                    None, lambda: browser_control(
                        args.get("action"),
                        args.get("url"),
                        args.get("query")
                    ))
                result = r or "Tamam."

            elif name == "system_action":
                r = await loop.run_in_executor(
                    None, lambda: system_action(args.get("action", ""), args.get("target", ""), args.get("destination", "")))
                result = r or "İşlem başarıyla çalıştı."

            elif name == "play_media":
                r = await loop.run_in_executor(
                    None,
                    lambda: play_media(
                        args.get("query", ""),
                        args.get("provider", "auto"),
                        bool(args.get("autoplay", True)),
                    ),
                )
                result = r or "Medya oynatma başlatıldı."

            elif name == "get_youtube_channel_report":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_youtube_channel_report(
                        args.get("query", "overview"),
                        args.get("handle", ""),
                        int(args.get("video_limit", 6) or 6),
                    ),
                )
                result = r or "YouTube kanal raporu alindi."

            elif name == "analyze_screen":
                r = await loop.run_in_executor(
                    None,
                    lambda: analyze_screen(
                        args.get("query", "Ekranda ne var?"),
                        args.get("target", "active_window"),
                    ),
                )
                result = r or "Ekran analizi tamamlandi."

            elif name == "send_whatsapp_message":
                r = await loop.run_in_executor(
                    None,
                    lambda: send_whatsapp_message(
                        args.get("message", ""),
                        args.get("phone_number", ""),
                        args.get("recipient_name", ""),
                        bool(args.get("send_now", False)),
                        args.get("app_target", "auto"),
                    ),
                )
                result = r or "WhatsApp işlemi tamamlandı."

            elif name == "save_whatsapp_contact":
                r = await loop.run_in_executor(
                    None,
                    lambda: save_whatsapp_contact(
                        args.get("display_name", ""),
                        args.get("phone_number", ""),
                        args.get("aliases", ""),
                    ),
                )
                result = r or "WhatsApp kişisi kaydedildi."

            elif name == "rag_ingest":
                r = await loop.run_in_executor(
                    None,
                    lambda: ingest_documents(
                        args.get("folder_path", ""),
                    ),
                )
                result = r or "Doküman yükleme tamamlandı."

            elif name == "rag_query":
                r = await loop.run_in_executor(
                    None,
                    lambda: query_documents(
                        args.get("question", ""),
                        int(args.get("top_k", 5) or 5),
                    ),
                )
                result = r or "Doküman sorgusu tamamlandı."

            elif name == "rag_list_sources":
                r = await loop.run_in_executor(
                    None,
                    lambda: list_indexed_sources(),
                )
                result = r or "Kaynak listesi alındı."

            elif name == "rag_clear":
                r = await loop.run_in_executor(
                    None,
                    lambda: rag_clear_index(),
                )
                result = r or "RAG indeksi temizlendi."

            else:
                result = f"Bilinmeyen araç: {name}"

        except Exception as e:
            result = f"Hata: {e}"
            had_exception = True
            traceback.print_exc()
            self.speak_error(name, e)

        tool_failed = self._result_looks_like_error(result)
        if tool_failed:
            if not had_exception:
                self.ui.set_state("ERROR")
        elif self._should_play_success_sfx(name, args, result):
            self.ui.play_success_sfx()

        if not tool_failed and not getattr(self.ui, 'muted', False):
            self.ui.set_state("LISTENING")

        print(f"[B.A.R.B.A.R.O.S] 📤 {name} → {str(result)[:80]}")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        consecutive_timeouts = 0
        while True:
            msg = await self.out_queue.get()
            retry_count = 0
            max_retries = 2
            while retry_count <= max_retries:
                try:
                    await asyncio.wait_for(
                        self.session.send_realtime_input(media=msg),
                        timeout=SEND_TIMEOUT,
                    )
                    consecutive_timeouts = 0  # Başarılı — counter reset
                    break
                except asyncio.TimeoutError:
                    retry_count += 1
                    consecutive_timeouts += 1
                    print(f"[B.A.R.B.A.R.O.S] ⏱️ Ses gönderim timeout (retry {retry_count}/{max_retries})")
                    if retry_count <= max_retries:
                        await asyncio.sleep(0.5)  # Kısa bekleme sonra retry
                    else:
                        print(f"[B.A.R.B.A.R.O.S] ❌ {max_retries} retry sonra timeout — bağlantı koptu")
                        raise ConnectionError("send_realtime_input timeout after retries")
                except Exception as e:
                    print(f"[B.A.R.B.A.R.O.S] ❌ Ses gönderim hatası: {e}")
                    consecutive_timeouts = 0
                    raise

    async def _listen_audio(self):
        print("[B.A.R.B.A.R.O.S] 🎤 Mikrofon başladı")
        stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT, channels=CHANNELS,
            rate=SEND_SAMPLE_RATE, input=True,
            frames_per_buffer=CHUNK_SIZE,
        )
        try:
            while True:
                data = await asyncio.to_thread(
                    stream.read, CHUNK_SIZE, exception_on_overflow=False)
                with self._speaking_lock:
                    jarvis_speaking = self._is_speaking
                if not jarvis_speaking and not getattr(self.ui, 'muted', False) and not self._paused:
                    # Queue doluysa, az timeout ile bekle veya yeni veriyi koy
                    try:
                        await asyncio.wait_for(
                            self.out_queue.put({"data": data, "mime_type": "audio/pcm"}),
                            timeout=0.5
                        )
                    except asyncio.TimeoutError:
                        # Queue hala doluysa, en eski veriyi at ve yenisini koy (backpressure handling)
                        try:
                            self.out_queue.get_nowait()
                            self.out_queue.put_nowait({"data": data, "mime_type": "audio/pcm"})
                        except asyncio.QueueEmpty:
                            pass
                        except asyncio.QueueFull:
                            pass  # Yine doluysa, bu chunk'ı skip et
        except Exception as e:
            print(f"[B.A.R.B.A.R.O.S] ❌ Mikrofon: {e}")
            raise
        finally:
            stream.close()

    async def _receive_audio(self):
        print("[B.A.R.B.A.R.O.S] 👂 Alım başladı")
        out_buf, in_buf = [], []
        output_noise = False
        output_noise_samples = []
        try:
            while True:
                async for response in self.session.receive():
                    if response.data:
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            self.set_speaking(True)
                            raw_txt = sc.output_transcription.text.strip()
                            if raw_txt:
                                txt, had_noise = self._clean_transcript_text(raw_txt)
                                if had_noise:
                                    output_noise = True
                                    if len(output_noise_samples) < 4:
                                        output_noise_samples.append(raw_txt)
                                if txt:
                                    out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                in_buf.append(txt)
                                self.ui.mark_user_activity(True)

                        if sc.turn_complete:
                            # Sentinel: ses kuyruğundaki tüm chunk'lar çalındıktan
                            # sonra SPEAKING → LISTENING geçişi yapılsın.
                            self.audio_in_queue.put_nowait(None)

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"Siz: {full_in}")
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"B.A.R.B.A.R.O.S: {full_out}")
                                if output_noise_samples:
                                    self.ui.write_debug(
                                        "Kısmen filtrelenen ses transcripti: " + " | ".join(output_noise_samples),
                                        level="WARN",
                                    )
                            elif output_noise:
                                self.ui.write_log("ERR: B.A.R.B.A.R.O.S sesli yanıtını çözümlerken bir hata oluştu.")
                                if output_noise_samples:
                                    self.ui.write_debug(
                                        "Filtrelenen ham transcript: " + " | ".join(output_noise_samples),
                                        level="WARN",
                                    )
                                self.ui.set_state("ERROR")
                            out_buf = []
                            output_noise = False
                            output_noise_samples = []

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[B.A.R.B.A.R.O.S] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses)

        except Exception as e:
            print(f"[B.A.R.B.A.R.O.S] ❌ Alım: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[B.A.R.B.A.R.O.S] 🔊 Ses çalma başladı")
        stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT, channels=CHANNELS,
            rate=RECV_SAMPLE_RATE, output=True,
        )
        try:
            while True:
                chunk = await self.audio_in_queue.get()
                if chunk is None:
                    # turn_complete sentinel — tüm ses çalındı, dinlemeye geç
                    self.set_speaking(False)
                    continue
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[B.A.R.B.A.R.O.S] ❌ Ses: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.close()

    async def _keepalive(self):
        """Session timeout'unu önlemek için periyodik keepalive sinyali gönderir."""
        # 100ms sessiz PCM verisi (16kHz, 16-bit mono = 3200 byte)
        silent_chunk = b'\x00' * 3200
        fail_count = 0
        consecutive_quick_fails = 0
        while True:
            await asyncio.sleep(KEEPALIVE_INTERVAL)
            try:
                if self.session and not self._paused:
                    await asyncio.wait_for(
                        self.session.send_realtime_input(
                            media={"data": silent_chunk, "mime_type": "audio/pcm"}
                        ),
                        timeout=SEND_TIMEOUT,
                    )
                    fail_count = 0  # Başarılı — sayacı sıfırla
                    consecutive_quick_fails = 0
                    print("[B.A.R.B.A.R.O.S] 💓 Keepalive gönderildi")
            except asyncio.TimeoutError:
                fail_count += 1
                consecutive_quick_fails += 1
                print(f"[B.A.R.B.A.R.O.S] ⏱️ Keepalive timeout ({fail_count}/{KEEPALIVE_FAIL_THRESHOLD})")
                # Ardışık hızlı fail'leri (ağ problemleri) log et ama daha toleranslı ol
                if consecutive_quick_fails >= 2:
                    print(f"[B.A.R.B.A.R.O.S] ⚠️ Ardışık keepalive timeout'ları — ağ unstable olabilir")
                if fail_count >= KEEPALIVE_FAIL_THRESHOLD:
                    print(f"[B.A.R.B.A.R.O.S] ❌ {KEEPALIVE_FAIL_THRESHOLD} keepalive timeout — bağlantı koptu sayılıyor")
                    raise ConnectionError(f"{KEEPALIVE_FAIL_THRESHOLD} consecutive keepalive timeouts")
            except Exception as e:
                print(f"[B.A.R.B.A.R.O.S] ❌ Keepalive hatası: {e}")
                consecutive_quick_fails = 0
                raise  # TaskGroup yakalar, yeniden bağlanma tetiklenir

    async def _midnight_checker(self):
        """Her dakika saati kontrol eder, 00:00 ise bildirim atar."""
        last_triggered_date = None
        while True:
            now = datetime.datetime.now()
            if now.hour == 0 and now.minute == 0:
                if last_triggered_date != now.date():
                    if toast is not None:
                        try:
                            toast("B.A.R.B.A.R.O.S", "Gece geç oldu yatacak mısın?")
                        except Exception as e:
                            print(f"[B.A.R.B.A.R.O.S] ❌ Bildirim hatası: {e}")
                    else:
                        print("[B.A.R.B.A.R.O.S] ⚠️ win11toast yüklü değil. Bildirim atılamadı.")
                    last_triggered_date = now.date()
            await asyncio.sleep(30)

    async def run(self):
        client = genai.Client(
            api_key=get_api_key(),
            http_options={"api_version": "v1alpha"}
        )

        while True:
            # Duraklatılmışsa bağlanma, bekle
            if self._paused:
                await asyncio.sleep(1)
                continue

            try:
                print(f"[B.A.R.B.A.R.O.S] 🔌 Bağlanıyor... (sonraki deneme: {self._reconnect_delay}s)")
                self.ui.set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=15)

                    print("[B.A.R.B.A.R.O.S] ✅ Bağlandı.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: B.A.R.B.A.R.O.S hazır. Dinliyorum...")
                    self._reconnect_delay = RECONNECT_BASE_DELAY  # Başarılı bağlantı — delay sıfırla

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._keepalive())
                    tg.create_task(self._midnight_checker())

            except Exception as e:
                err_str = str(e)
                print(f"[B.A.R.B.A.R.O.S] ⚠️ {err_str}")
                traceback.print_exc()
                self._cleanup_session()

                # Hata türüne göre delay stratejisini belirle
                is_timeout = any(x in err_str.lower() for x in ["timeout", "keepalive", "timed out"])
                is_network = any(x in err_str.lower() for x in ["connection", "network", "refused"])
                
                if is_timeout or is_network:
                    # Ağ sorunu = hızlı retry ile başla (exponential backoff daha yumuşak)
                    if self._reconnect_delay == RECONNECT_BASE_DELAY:
                        delay = RECONNECT_BASE_DELAY  # İlk deneme: 3s bekle
                    else:
                        delay = min(self._reconnect_delay * 1.5, RECONNECT_MAX_DELAY)
                else:
                    # Diğer hatalar = normal exponential backoff
                    delay = min(self._reconnect_delay * 2, RECONNECT_MAX_DELAY)

                self.ui.write_log(f"ERR: Bağlantı kesildi — {delay:.0f}s sonra yeniden denenecek.")
                self.ui.set_state("ERROR")
                print(f"[B.A.R.B.A.R.O.S] 🔄 {delay:.0f} saniyede yeniden bağlanıyor...")
                await asyncio.sleep(delay)
                self._reconnect_delay = delay


def main():
    if os.environ.get("TERM_PROGRAM") == "vscode":
        print("[B.A.R.B.A.R.O.S] VS Code icinden baslatildi.")

    ui = JarvisUI()

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Kapatılıyor...")

    threading.Thread(target=runner, daemon=True).start()

    wake_listener = WakeGestureListener(on_wake=ui.wake_up)
    wake_listener.start()

    ui.root.mainloop()


if __name__ == "__main__":
    main()
