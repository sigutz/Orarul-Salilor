import os
import json
import time
import hashlib
import requests
from bs4 import BeautifulSoup

STATE_FILE = "state.json"
URL_FMI = "https://fmi.unibuc.ro/orar/"

def get_last_update_info():
    """
    Descarcă HTML-ul de la FMI, găsește link-ul de bit.ly și generează 
    o amprentă digitală (hash) a actualizării pentru a detecta schimbările.
    """
    try:
        # Setăm un User-Agent fals pentru a părea că suntem un browser real.
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        # 1. Descărcăm pagina
        response = requests.get(URL_FMI, headers=headers, timeout=10)
        response.raise_for_status() 

        # 2. Parsăm HTML-ul
        soup = BeautifulSoup(response.text, 'html.parser')

        # 3. Căutăm primul link de tip bit.ly
        target_link = None
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            # Căutăm specific scurtătura bit.ly cerută
            if "bit.ly" in href:
                target_link = href
                break

        if not target_link:
            print("[-] Nu am găsit niciun link bit.ly pe pagina FMI.")
            return None, None

        # 4. Căutăm textul care indică ultima actualizare
        update_text = ""
        for tag in soup.find_all(['p', 'span', 'strong', 'div']):
            text_continut = tag.get_text(strip=True).lower()
            if "actualizat" in text_continut or "update" in text_continut:
                update_text = text_continut
                break 
                
        # Fallback: dacă nu scrie explicit "actualizat", luăm o bucată din pagina principală
        if not update_text:
            main_content = soup.find('main') or soup.find('div', class_='entry-content')
            if main_content:
                update_text = main_content.get_text(strip=True)[:500] 

        # 5. Generăm "Timestamp-ul" (Hash-ul Unic)
        raw_signature = f"{target_link}_{update_text}"
        version_hash = hashlib.md5(raw_signature.encode('utf-8')).hexdigest()

        return version_hash, target_link

    except requests.exceptions.RequestException as e:
        print(f"[-] Eroare de rețea la accesarea site-ului FMI: {e}")
        return None, None
    except Exception as e:
        print(f"[-] Eroare neașteptată la parsarea HTML: {e}")
        return None, None

def should_update(current_version_hash):
    """
    Compară hash-ul curent al site-ului cu cel salvat local.
    """
    if not os.path.exists(STATE_FILE):
        return True
    
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            saved_version_hash = data.get("timestamp")
            
        return current_version_hash != saved_version_hash
    except (json.JSONDecodeError, FileNotFoundError):
        return True

def save_state(version_hash, target_link):
    """
    Salvează pe disk amprenta noii versiuni a site-ului.
    """
    state_data = {
        "timestamp": version_hash,
        "link": target_link,
        "last_checked": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=4)

# ==================================================================
# BLOC DE TESTARE (Se execută doar când rulezi acest fișier direct)
# ==================================================================
if __name__ == "__main__":
    print("=== TESTARE SCRAPER ORAR FMI ===")
    print(f"[*] Accesare {URL_FMI} ...\n")
    
    hash_versiune, link_gasit = get_last_update_info()
    
    if hash_versiune and link_gasit:
        print(f"[+] Link extras: {link_gasit}")
        print(f"[+] Amprentă versiune (Hash): {hash_versiune}")
        
        # Verificăm dacă avem deja acest hash salvat în state.json
        necesita_update = should_update(hash_versiune)
        
        print(f"\n[?] Necesită actualizare scriptul principal? -> {'DA' if necesita_update else 'NU (Avem deja ultima versiune)'}")
        
        # Opțional: Dacă ai vrea să-l forțezi să salveze starea din test, ai decomenta linia de mai jos:
        # save_state(hash_versiune, link_gasit)
    else:
        print("[-] Test eșuat. Datele nu au putut fi extrase.")