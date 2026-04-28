import time
import os
import cv2
import glob
from playwright.sync_api import sync_playwright, TimeoutError

def capture_orar_pages(drive_url, output_dir="data/screenshots"):
    """
    Folosește Atributele ARIA pentru a naviga prin Google Drive,
    dând click pe fiecare miniatură și capturând vizualizatorul central.
    Inclusiv fix pentru redirect-ul bit.ly.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome')
        # Folosim o rezoluție mare și factor de scară 2x (Retina) pentru ca AI-ul să poată citi perfect
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            device_scale_factor=2 
        )
        page = context.new_page()

        print(f"[*] Navigare către: {drive_url}")
        
        # Eliminăm networkidle pentru a nu ne bloca în redirect
        page.goto(drive_url)
        
        # --- FIX PENTRU REDIRECTUL BIT.LY ---
        print("[*] Se așteaptă redirecționarea către Google Drive...")
        try:
            page.wait_for_url("**drive.google.com/**", timeout=30000)
            print(f"[+] Redirecționare reușită! URL curent: {page.url.split('?')[0]}...")
        except TimeoutError:
            print("[-] EROARE: Timpul de așteptare a expirat la redirect.")
            browser.close()
            return []

        # Așteptăm încărcarea inițială greoaie a UI-ului din Drive
        time.sleep(6) 

        print("[*] Scanare după elemente ARIA (miniaturi)...")
        
        # 1. Căutăm lista de miniaturi (rolul 'option' este standardul Google aici)
        thumbnails = page.locator('li[role="option"]').all()
        
        # 2. Dacă nu le găsim, înseamnă că Google le-a ascuns într-un Iframe. Îl căutăm:
        target_frame = page
        if not thumbnails:
            for frame in page.frames:
                thumbs_in_frame = frame.locator('li[role="option"]').all()
                if thumbs_in_frame:
                    thumbnails = thumbs_in_frame
                    target_frame = frame # Mutăm "privirea" scriptului în acest frame
                    print("[*] Elementele au fost găsite într-un Iframe ascuns.")
                    break

        if not thumbnails:
            print("[-] EROARE: Nu am putut găsi nicio pagină/miniatură. Drive a schimbat interfața sau cere logare.")
            # Screenshot de debug ca să vedem unde s-a blocat
            page.screenshot(path=f"{output_dir}/00_debug_error.png")
            browser.close()
            return []

        print(f"[*] SUCCES: Am detectat {len(thumbnails)} pagini/miniaturi.")
        
        # Găsim containerul central (cel mare, unde citim textul)
        main_viewer = target_frame.locator('div[role="main"]').first
        
        captured_files = []

        for i, thumb in enumerate(thumbnails):
            print(f"  -> Procesare pagina {i+1} din {len(thumbnails)}...")
            
            # Click pe miniatură pentru a forța încărcarea în centru
            thumb.scroll_into_view_if_needed()
            thumb.click()
            
            # CRITIC: Așteptăm 3 secunde pentru ca pagina mare să devină clară (Google aplică un filtru de blur inițial)
            time.sleep(3) 
            
            file_path = f"{output_dir}/pag_{i+1:02d}.png"
            
            # Facem screenshot. Dacă găsim containerul principal, face ss doar pe el.
            # Dacă nu, facem screenshot la toată pagina.
            try:
                main_viewer.screenshot(path=file_path)
            except Exception:
                target_frame.screenshot(path=file_path)
                
            captured_files.append(file_path)
            print(f"  [+] Salvat: {file_path}")

        browser.close()
        return captured_files

def crop_screenshots_fixed(input_dir="data/screenshots", output_dir="data/processed_ss"):
    """
    Decupează screenshot-urile folosind coordonatele chirurgicale testate,
    aplicând un decalaj specific doar pentru ultima pagină.
    Sortează fișierele NUMERIC, nu alfabetic.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Coordonatele TALE de bază
    Y_START = 260   
    Y_END = 1380    
    X_START = 1270  
    X_END = 2880   

    # --- AJUSTARE PENTRU ULTIMA PAGINĂ ---
    Y_OFFSET_LAST_PAGE = 630

    # Căutăm fișierele
    raw_screenshots = glob.glob(os.path.join(input_dir, "pag_*.png"))
    
    # SORTARE NUMERICĂ: Extragem numărul din "pag_100.png" și sortăm după el
    screenshots = sorted(
        raw_screenshots, 
        key=lambda f: int(os.path.basename(f).replace('pag_', '').replace('.png', ''))
    )
    
    processed_files = []
    total_images = len(screenshots)

    print(f"[*] Decupare (Fixed Crop) pentru {total_images} imagini...")
    
    for idx, img_path in enumerate(screenshots):
        img = cv2.imread(img_path)
        if img is None:
            continue
        
        # Verificăm dacă suntem la ultima imagine din listă (acum va fi mereu pag_100.png)
        if idx == total_images - 1:
            current_y_start = Y_START + Y_OFFSET_LAST_PAGE
            current_y_end = Y_END + Y_OFFSET_LAST_PAGE
            print(f"  [!] Se aplică crop decalat pentru ultima pagină ({os.path.basename(img_path)}): +{Y_OFFSET_LAST_PAGE}px pe axa Y")
        else:
            current_y_start = Y_START
            current_y_end = Y_END

        try:
            # Aplicăm tăierea cu coordonatele dinamice
            cropped_img = img[current_y_start:current_y_end, X_START:X_END]
            filename = os.path.basename(img_path)
            output_path = os.path.join(output_dir, filename)
            
            cv2.imwrite(output_path, cropped_img)
            processed_files.append(output_path)
            print(f"  [+] Decupat și salvat: {output_path}")
        except Exception as e:
            print(f"  [-] Eroare la decupare {img_path}: {e}")
            
    return processed_files

# ==================================================================
# BLOC DE TESTARE / RULARE MANUALĂ (Se execută doar când rulezi direct acest fișier)
# ==================================================================
if __name__ == "__main__":
    print("=== START DECUPARE MANUALĂ (FĂRĂ RE-CAPTURARE) ===")
    
    # Asigură-te că folderele există relativ la de unde rulezi comanda
    input_folder = "data/screenshots"
    output_folder = "data/processed_ss"
    
    if not os.path.exists(input_folder) or len(glob.glob(os.path.join(input_folder, "pag_*.png"))) == 0:
        print(f"[-] EROARE: Nu am găsit poze în '{input_folder}'. Rulează mai întâi captura.")
    else:
        rezultat = crop_screenshots_fixed(input_dir=input_folder, output_dir=output_folder)
        print(f"[+] Am decupat cu succes {len(rezultat)} imagini!")