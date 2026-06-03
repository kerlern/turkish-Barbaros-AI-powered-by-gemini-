"""
Terminal komutu çalıştırma — Windows cmd/PowerShell
Güvenlik Filtresi (Sandbox / Blacklist) Eklenmiştir.
"""

import subprocess
import re

# Tehlikeli işlemleri tespit edecek Regex filtreleri (Gelişmiş Blacklist)
SECURITY_FILTERS = [
    # Disk, Format ve Dosya Silme İşlemleri (CMD ve PowerShell Alias'ları dâhil)
    r"\b(rm|rmdir|rd|del|erase|remove-item|ri)\b",
    r"\b(format|diskpart|bcdedit|chkdsk|vssadmin)\b",
    
    # Kapatma ve Yeniden Başlatma
    r"\b(shutdown|reboot|halt|poweroff|logoff)\b",
    
    # Sistem Yapılandırması, Servisler ve İzinler
    r"\b(reg|schtasks|sc|taskkill|tskill|icacls|cacls|takeown)\b",
    r"\b(net|netsh|netstat|arp|route)\b",
    
    # Payload İndirme ve Dış Bağlantı Araçları (PowerShell cmdlet'leri ve alias'ları dâhil)
    r"\b(curl|wget|certutil|bitsadmin|ftp|tftp|invoke-webrequest|iwr|downloadfile|downloadstring)\b",
    
    # Script motorları üzerinden gizli/zararlı parametreler (-enc, Invoke-WebRequest vb.)
    r"\b(powershell|pwsh|cmd|wscript|cscript|mshta)\b.*(?:-enc|-command|-c|invoke|iex|download|hidden)",
    
    # Python üzerinden inline script (Indirect Execution bypass'ı)
    r"\bpython(?:3)?\s+(?:-c|-m)\b"
]

def is_safe_command(command: str) -> bool:
    # 1. Küçük harfe çevir ve CMD kaçış/gizleme karakterlerini temizle (Obfuscation temizliği)
    clean_cmd = command.lower().replace("^", "").replace('"', '').replace("'", "")
    
    # 2. Regex filtrelerini re.IGNORECASE ile tara
    for pattern in SECURITY_FILTERS:
        if re.search(pattern, clean_cmd, re.IGNORECASE):
            return False
            
    return True

def shell_run(command: str, timeout: int = 30) -> str:
    if not command:
        return "Komut belirtilmedi."

    # 1. AŞAMA: Gelişmiş Karaliste (Blacklist) & Obfuscation Kontrolü
    if not is_safe_command(command):
        return "[B.A.R.B.A.R.O.S] ⚠️ Güvenlik duvarı ihlali! Bu komutu çalıştırmama izin verilmiyor, kral."

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        output = (result.stdout + result.stderr).strip()
        if not output:
            return "Komut başarıyla çalıştı (çıktı yok)."
        
        # Çıktı çok uzunsa token limitini korumak için kes
        if len(output) > 800:
            output = output[:800] + "\n... [ÇIKTI GÜVENLİK/TOKEN NEDENİYLE KISALTILDI]"
            
        return output
        
    except subprocess.TimeoutExpired:
        return f"Komut zaman aşımına uğradı ({timeout}s)."
    except Exception as e:
        return f"Hata: {e}"
