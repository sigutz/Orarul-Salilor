import sys
import os
from src.watcher import get_last_update_info, should_update, save_state
from src.extractor import capture_orar_pages, crop_screenshots_fixed

def run_capture_and_crop():
    print("[1/3] Verificare actualizări site...")
    timestamp, drive_link = get_last_update_info()

    if not timestamp or not drive_link:
        print("[-] Nu s-a putut obține timestamp-ul sau link-ul.")
        return

    # Șterge state.json dacă vrei să forțezi o rulare proaspătă
    if not should_update(timestamp):
        print(f"[!] Orarul este deja la zi. Stop.")
        return

    print(f"[+] Link găsit! Se pornește extragerea...")

    print("[2/3] Pornire Headless Browser (Playwright) pentru captură...")
    raw_screenshots = capture_orar_pages(drive_link)
    
    if not raw_screenshots:
        print("[-] Nu am reușit să capturez nicio pagină.")
        return

    print("[3/3] Decupare imagini (Crop la pixeli ficși)...")
    cropped_screenshots = crop_screenshots_fixed()

    save_state(timestamp, drive_link)
    
    print(f"\n[SUCCES] Gata! Am salvat și decupat {len(cropped_screenshots)} imagini în 'data/processed_ss/'.")
    print("-> Rulează 'python3 src/ai_generator.py' pentru a extrage JSON-urile cu Qwen!")

if __name__ == "__main__":
    run_capture_and_crop()