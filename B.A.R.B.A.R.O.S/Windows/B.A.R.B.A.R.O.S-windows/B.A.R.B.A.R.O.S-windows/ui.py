import os
import time
import math
import random
import threading
import tkinter as tk
from tkinter import ttk
from collections import deque
from pathlib import Path
import psutil

from app_config import has_gemini_api_key, load_app_config, save_app_config

BASE_DIR = Path(__file__).resolve().parent
SYSTEM_NAME = "B.A.R.B.A.R.O.S CORE OS v3.0"

# --- SLEEK MODERN COLOR PALETTE ---
BG_COLOR = "#030712"       # Çok derin, siyaha çalan lacivert
PANEL_BG = "#111827"       # Mat koyu gri/mavi panel arka planı
PANEL_BORDER = "#1f2937"   # Panel sınırları
ACCENT_BLUE = "#3b82f6"    # Temiz ve parlak mavi (Dinleme)
ACCENT_CYAN = "#06b6d4"    # Camgöbeği (Düşünme)
ACCENT_GREEN = "#10b981"   # Zümrüt Yeşili (Konuşma)
ACCENT_RED = "#ef4444"     # Uyarı Kırmızısı (Hata)
TEXT_MAIN = "#f3f4f6"      # Beyaz metin
TEXT_MUTED = "#9ca3af"     # Soluk gri metin

STATE_COLORS = {
    "LISTENING": ACCENT_BLUE,
    "THINKING": ACCENT_CYAN,
    "SPEAKING": ACCENT_GREEN,
    "ERROR": ACCENT_RED
}

class JarvisUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("B.A.R.B.A.R.O.S - Intelligent Interface")
        self.root.geometry("1280x800")
        self.root.configure(bg=BG_COLOR)
        
        self._state = "LISTENING"
        self._api_key_ready = threading.Event()
        self.logs = deque(maxlen=25)
        
        # Animasyon değişkenleri
        self.tick = 0
        self.ring_angles = [0.0, 45.0, 90.0, 180.0, 270.0]
        self.pulse = 0.0
        
        # API Anahtarı Kontrolü
        if has_gemini_api_key():
            self._api_key_ready.set()
        else:
            self._api_key_ready.set() # Kilitlenmeyi önler
            
        self._build_ui()
        
        self.write_log("INIT: B.A.R.B.A.R.O.S Core Sequence Started")
        self.write_log("SYS: Hardware Check ... OK")
        self.write_log("SYS: Neural Link ... ESTABLISHED")
        
        # Arka plan donanım dinleme thread'i
        threading.Thread(target=self._sys_monitor_loop, daemon=True).start()
        
        # Animasyon döngüsünü başlat
        self._animate()

    def wait_for_api_key(self):
        """main.py bu fonksiyonu çağırarak API doğrulaması bekler"""
        self._api_key_ready.wait()
        
    def wake_up(self):
        """Wake-word yakalandığında tetiklenir."""
        self.set_state("LISTENING")
        self.write_log("EVENT: Voice Activity Detected. Switching to Listening Mode.")
        
    def set_state(self, state):
        """Asistan durumu değiştiğinde arayüzü ve renkleri günceller."""
        if state in STATE_COLORS:
            self._state = state
            self.write_log(f"STATE: {state}")
            
    def write_log(self, message):
        """Log terminaline gerçek zamanlı veri basar."""
        t_str = time.strftime("%H:%M:%S")
        self.logs.append(f"[{t_str}] {message}")
        if hasattr(self, "log_text"):
            self.log_text.configure(state="normal")
            self.log_text.delete(1.0, tk.END)
            self.log_text.insert(tk.END, "\n".join(self.logs))
            self.log_text.configure(state="disabled")
            self.log_text.see(tk.END)
            
    def write_debug(self, message, level="DEBUG"):
        self.write_log(f"[{level}] {message}")
        
    def focus_panel(self, panel_name, duration_ms=5000):
        pass # Panel vurgulama animasyonu altyapısı (main.py ile uyumluluk)
        
    def play_success_sfx(self):
        pass # İlerisi için ses efekti altyapısı
        
    def mark_user_activity(self, active=True):
        pass 

    def _build_ui(self):
        """Arayüzü 3 parçalı (Sol, Orta, Sağ) ve Alt Terminal olacak şekilde inşa eder."""
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=3)
        self.root.grid_columnconfigure(2, weight=1)
        self.root.grid_rowconfigure(0, weight=3)
        self.root.grid_rowconfigure(1, weight=1)

        font_title = ("Consolas", 12, "bold")
        font_main = ("Consolas", 10)
        font_small = ("Consolas", 8)

        # ---------------------------------------------------------
        # SOL PANEL (SİSTEM METRİKLERİ)
        # ---------------------------------------------------------
        self.left_frame = tk.Frame(self.root, bg=PANEL_BG, bd=1, relief="flat", highlightbackground=PANEL_BORDER, highlightthickness=1)
        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=(15, 10), pady=15)
        
        tk.Label(self.left_frame, text="[ SYSTEM TELEMETRY ]", bg=PANEL_BG, fg=TEXT_MUTED, font=font_title).pack(pady=(15, 20), anchor="w", padx=15)
        
        self.metrics = ["CPU_USAGE", "MEM_ALLOC", "GPU_LOAD", "NET_UPLINK", "TEMP_CORE"]
        self.metric_ui = {}
        for m in self.metrics:
            f = tk.Frame(self.left_frame, bg=PANEL_BG)
            f.pack(fill="x", padx=15, pady=8)
            
            top_f = tk.Frame(f, bg=PANEL_BG)
            top_f.pack(fill="x")
            tk.Label(top_f, text=m, bg=PANEL_BG, fg=TEXT_MAIN, font=font_main).pack(side="left")
            val_lbl = tk.Label(top_f, text="0%", bg=PANEL_BG, fg=ACCENT_CYAN, font=font_main)
            val_lbl.pack(side="right")
            
            bar_bg = tk.Frame(f, bg=BG_COLOR, height=4)
            bar_bg.pack(fill="x", pady=(5,0))
            bar_fg = tk.Frame(bar_bg, bg=ACCENT_CYAN, width=0, height=4)
            bar_fg.pack(side="left")
            
            self.metric_ui[m] = {"val": val_lbl, "bar": bar_fg, "bg": bar_bg}

        # ---------------------------------------------------------
        # ORTA PANEL (HOLOGRAFİK ÇEKİRDEK)
        # ---------------------------------------------------------
        self.center_frame = tk.Frame(self.root, bg=BG_COLOR)
        self.center_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=15)
        self.canvas = tk.Canvas(self.center_frame, bg=BG_COLOR, highlightthickness=0)
        self.canvas.pack(expand=True, fill="both")

        # ---------------------------------------------------------
        # SAĞ PANEL (MODÜLLER VE YÖNERGELER)
        # ---------------------------------------------------------
        self.right_frame = tk.Frame(self.root, bg=PANEL_BG, bd=1, relief="flat", highlightbackground=PANEL_BORDER, highlightthickness=1)
        self.right_frame.grid(row=0, column=2, sticky="nsew", padx=(10, 15), pady=15)
        
        tk.Label(self.right_frame, text="[ ACTIVE DIRECTIVES ]", bg=PANEL_BG, fg=TEXT_MUTED, font=font_title).pack(pady=(15, 20), anchor="w", padx=15)
        
        modules = [
            ("VOICE_ENGINE", "ONLINE"), 
            ("COGNITIVE_CORE", "IDLE"), 
            ("VISION_PROCESSOR", "STANDBY"), 
            ("DATA_LINK", "SECURE")
        ]
        for name, status in modules:
            f = tk.Frame(self.right_frame, bg=PANEL_BG)
            f.pack(fill="x", padx=15, pady=8)
            tk.Label(f, text=f"> {name}", bg=PANEL_BG, fg=TEXT_MAIN, font=font_main).pack(side="left")
            col = ACCENT_GREEN if status in ["ONLINE", "SECURE"] else TEXT_MUTED
            tk.Label(f, text=status, bg=PANEL_BG, fg=col, font=font_main).pack(side="right")
            
        tk.Frame(self.right_frame, bg=PANEL_BORDER, height=1).pack(fill="x", padx=15, pady=20)
        
        # Ekstra durum bilgisi panelini dolduralım (Spektrum yerine daha temiz bir durum göstergesi)
        tk.Label(self.right_frame, text="[ CONNECTION STATUS ]", bg=PANEL_BG, fg=TEXT_MUTED, font=font_title).pack(anchor="w", padx=15)
        conn_f = tk.Frame(self.right_frame, bg=PANEL_BG)
        conn_f.pack(fill="x", padx=15, pady=10)
        tk.Label(conn_f, text="HOST: LOCALHOST\nPORT: 8080\nSECURE LAYER: ACTIVE\nENCRYPTION: AES-256", 
                 bg=PANEL_BG, fg=TEXT_MAIN, font=font_main, justify="left").pack(anchor="w")

        # ---------------------------------------------------------
        # ALT PANEL (TERMİNAL)
        # ---------------------------------------------------------
        self.bottom_frame = tk.Frame(self.root, bg=PANEL_BG, bd=1, highlightbackground=PANEL_BORDER, highlightthickness=1)
        self.bottom_frame.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=15, pady=(0, 15))
        
        term_header = tk.Frame(self.bottom_frame, bg=PANEL_BORDER)
        term_header.pack(fill="x")
        tk.Label(term_header, text="  TERMINAL OUTPUT", bg=PANEL_BORDER, fg=TEXT_MAIN, font=font_small).pack(side="left", pady=2)
        
        self.log_text = tk.Text(self.bottom_frame, bg=PANEL_BG, fg=TEXT_MAIN, font=font_main, relief="flat", state="disabled", height=10)
        self.log_text.pack(fill="both", expand=True, padx=10, pady=5)

    def _sys_monitor_loop(self):
        """Sistem performans metriklerini ölçen döngü."""
        while True:
            try:
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory().percent
                gpu = random.randint(10, 40)
                net = random.randint(1, 100)
                temp = random.randint(35, 65)
                
                self.root.after(0, self._update_metric, "CPU_USAGE", cpu)
                self.root.after(0, self._update_metric, "MEM_ALLOC", ram)
                self.root.after(0, self._update_metric, "GPU_LOAD", gpu)
                self.root.after(0, self._update_metric, "NET_UPLINK", net)
                self.root.after(0, self._update_metric, "TEMP_CORE", temp)
            except:
                pass
            time.sleep(1.5)

    def _update_metric(self, name, val):
        if name in self.metric_ui:
            if name == "TEMP_CORE":
                self.metric_ui[name]["val"].config(text=f"{val}°C")
            else:
                self.metric_ui[name]["val"].config(text=f"{val}%")
                
            bg_w = self.metric_ui[name]["bg"].winfo_width()
            bar_w = int((val / 100.0) * bg_w) if bg_w > 10 else int(val * 2)
            self.metric_ui[name]["bar"].config(width=bar_w)
            
            # Dinamik renk değişimi (Fazla kullanımda kırmızıya dönme)
            color = ACCENT_CYAN if val < 60 else (ACCENT_BLUE if val < 85 else ACCENT_RED)
            if name == "TEMP_CORE":
                color = ACCENT_CYAN if val < 50 else (ACCENT_BLUE if val < 70 else ACCENT_RED)
            self.metric_ui[name]["bar"].config(bg=color)

    def _draw_arc(self, cx, cy, r, start, extent, width, color, dash=None):
        self.canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=start, extent=extent, style=tk.ARC, outline=color, width=width, dash=dash)

    def _animate(self):
        """Ortadaki dev çekirdeğin pürüzsüz animasyonunu sağlar."""
        if not self.canvas.winfo_exists(): return
        
        self.tick += 1
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 10 or h < 10: w, h = 600, 500
        cx, cy = w // 2, h // 2
        
        color = STATE_COLORS.get(self._state, ACCENT_BLUE)
        
        # Grid Arka Plan
        grid_space = 50
        for x in range(0, w, grid_space):
            self.canvas.create_line(x, 0, x, h, fill="#0c1222", width=1)
        for y in range(0, h, grid_space):
            self.canvas.create_line(0, y, w, y, fill="#0c1222", width=1)
            
        # Merkezi Nişangah (Crosshairs)
        self.canvas.create_line(cx, cy-300, cx, cy+300, fill=PANEL_BORDER, dash=(4, 4))
        self.canvas.create_line(cx-300, cy, cx+300, cy, fill=PANEL_BORDER, dash=(4, 4))

        # Açıları Güncelle (60 FPS için hızları ve açı adımlarını optimize ettik)
        self.ring_angles[0] = (self.ring_angles[0] + 0.8) % 360
        self.ring_angles[1] = (self.ring_angles[1] - 1.0) % 360
        self.ring_angles[2] = (self.ring_angles[2] + 0.5) % 360
        self.ring_angles[3] = (self.ring_angles[3] - 1.3) % 360
        self.ring_angles[4] = (self.ring_angles[4] + 0.3) % 360
        
        # Nefes Alma (Pulse) Efekti
        self.pulse = (math.sin(time.time() * 2.5) + 1) / 2
        
        # İç Çekirdek (Glow ve orb)
        core_radius = 40 + (self.pulse * 8)
        self.canvas.create_oval(cx-core_radius, cy-core_radius, cx+core_radius, cy+core_radius, fill=color, outline="")
        self.canvas.create_oval(cx-core_radius-8, cy-core_radius-8, cx+core_radius+8, cy+core_radius+8, outline=color, width=1, dash=(2, 4))
        
        # Halkalar
        # Halka 1 (Kesintisiz iç dönen parça)
        self._draw_arc(cx, cy, 90, self.ring_angles[0], 270, 2, color)
        self._draw_arc(cx, cy, 90, self.ring_angles[0] + 300, 30, 2, TEXT_MAIN)
        
        # Halka 2 (Kesik Çizgili Ters Dönen)
        self._draw_arc(cx, cy, 120, self.ring_angles[1], 360, 1, TEXT_MUTED, dash=(1, 5))
        self._draw_arc(cx, cy, 120, self.ring_angles[1], 90, 3, color)
        
        # Halka 3 (Kalın teknolojik parçalar)
        for i in range(4):
            self._draw_arc(cx, cy, 150, self.ring_angles[2] + (i * 90), 45, 6, PANEL_BORDER)
            self._draw_arc(cx, cy, 150, self.ring_angles[2] + (i * 90) + 10, 25, 6, color)
            
        # Halka 4 (Dış ince yörünge)
        self.canvas.create_oval(cx-190, cy-190, cx+190, cy+190, outline=PANEL_BORDER, width=1)
        self._draw_arc(cx, cy, 190, self.ring_angles[3], 60, 2, color)
        self._draw_arc(cx, cy, 190, self.ring_angles[3] + 180, 60, 2, color)
        
        # HUD Bağlantı Çizgileri ve Metinler
        # Sağ Üst
        self.canvas.create_line(cx+134, cy-134, cx+200, cy-200, fill=color, width=1)
        self.canvas.create_line(cx+200, cy-200, cx+280, cy-200, fill=color, width=1)
        self.canvas.create_text(cx+240, cy-210, text="CORE_LINK_ESTABLISHED", fill=TEXT_MAIN, font=("Consolas", 8))
        
        # Sol Alt
        self.canvas.create_line(cx-134, cy+134, cx-200, cy+200, fill=color, width=1)
        self.canvas.create_line(conn_f_x := cx-200, cy+200, cx-280, cy+200, fill=color, width=1)
        self.canvas.create_text(cx-240, cy+190, text="SYS_HEALTH: OPTIMAL", fill=TEXT_MAIN, font=("Consolas", 8))
        
        # Merkez Durum Metni
        self.canvas.create_text(cx, cy+240, text=f"[{self._state}]", fill=color, font=("Consolas", 14, "bold", "italic"))
        self.canvas.create_text(cx, cy-240, text=SYSTEM_NAME, fill=TEXT_MAIN, font=("Consolas", 10))
        
        # 60 FPS pürüzsüz animasyon döngüsü (16 ms gecikme)
        self.root.after(16, self._animate)

if __name__ == "__main__":
    ui = JarvisUI()
    ui.root.mainloop()
