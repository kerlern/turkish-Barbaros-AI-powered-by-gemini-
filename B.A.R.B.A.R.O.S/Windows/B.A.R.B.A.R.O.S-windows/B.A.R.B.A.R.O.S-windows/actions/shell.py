"""
Sistem işlemleri ve dosya yönetimi (Command Mapper / Sandboxed Proxy)
Güvenlik nedeniyle shell=True kullanımı tamamen kaldırılmış ve işlemler Python'un 
yerel kütüphanelerine (os, shutil, güvenli subprocess) devredilmiştir.
"""

import os
import shutil
import subprocess

def system_action(action: str, target: str = "", destination: str = "") -> str:
    """
    Güvenli sistem işlemleri yürütücüsü.
    action: İşlem türü (list_dir, copy, list_tasks vb.)
    target: Hedef dosya, klasör, process adı veya argüman
    destination: Varsa ikinci argüman (örn. kopyalama hedefi)
    """
    action = action.lower().strip()
    target = target.strip()
    destination = destination.strip()
    
    try:
        if action == "list_dir":
            if not target:
                target = "."
            if not os.path.exists(target):
                return f"Hata: Yol bulunamadı ({target})"
            if not os.path.isdir(target):
                return f"Hata: Belirtilen yol bir klasör değil ({target})"
                
            items = os.listdir(target)
            return f"Klasör İçeriği ({target}):\n" + "\n".join(items)
            
        elif action == "make_dir":
            if not target:
                return "Hata: Klasör adı belirtilmedi."
            os.makedirs(target, exist_ok=True)
            return f"Klasör oluşturuldu: {target}"
            
        elif action == "read_file":
            if not target or not os.path.isfile(target):
                return "Hata: Geçerli bir dosya belirtilmedi."
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(2000) # Sadece ilk 2000 karakteri oku (Token koruması)
            return f"Dosya İçeriği (ilk 2000 karakter):\n{content}"
            
        elif action == "copy":
            if not target or not destination:
                return "Hata: Hedef veya varış belirtilmedi."
            if os.path.isdir(target):
                shutil.copytree(target, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(target, destination)
            return f"Kopyalandı: {target} -> {destination}"
            
        elif action == "move":
            if not target or not destination:
                return "Hata: Hedef veya varış belirtilmedi."
            shutil.move(target, destination)
            return f"Taşındı: {target} -> {destination}"
            
        elif action == "delete":
            # GÜVENLİK: Kök dizin (C:\ vb.) silmeyi kesinlikle önle
            safe_target = os.path.abspath(target)
            if safe_target in ["C:\\", "D:\\", "E:\\", "C:/", "D:/", "E:/", "/"]:
                return "Hata: Kök sürücü silinemez! Güvenlik ihlali reddedildi."
            
            if os.path.isfile(target):
                os.remove(target)
            elif os.path.isdir(target):
                shutil.rmtree(target)
            else:
                return "Hata: Dosya veya klasör bulunamadı."
            return f"Silindi: {target}"
            
        elif action == "list_tasks":
            # Shell kullanılmadan process listesi alınır
            result = subprocess.run(["tasklist"], capture_output=True, text=True, errors="replace", shell=False)
            output = result.stdout
            
            # Eğer target varsa (Örn: "chrome"), sadece o kelimeyi içeren satırları döndür (Pipe simülasyonu)
            if target:
                lines = output.split('\n')
                filtered = [line for line in lines if target.lower() in line.lower()]
                output = "\n".join(filtered)
                if not output:
                    return f"'{target}' içeren işlem bulunamadı."
                    
            if len(output) > 1000:
                output = output[:1000] + "\n... [ÇIKTI KISALTILDI]"
            return output
            
        elif action == "ping":
            if not target:
                target = "google.com"
            result = subprocess.run(["ping", target], capture_output=True, text=True, errors="replace", shell=False)
            return result.stdout
            
        else:
            return f"Hata: Bilinmeyen sistem eylemi '{action}'"
            
    except Exception as e:
        return f"İşlem sırasında hata oluştu: {str(e)}"
