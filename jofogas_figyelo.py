import requests
import json
import os
import re
import csv
import time
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# Titkos adatok betöltése
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Linkek
JOFOGAS_URL = "https://ingatlan.jofogas.hu/fejer/haz?max_price=93000000&min_size=80&st=s"
OTP_URL = "https://www.otpip.hu/kereses?ertekesitestipusa=elado&ingatlantipusa=haz&allapot=uj-epitesu&elhelyezkedes=Velence%7CCITY%26G%C3%A1rdony%7CCITY%26P%C3%A1kozd%7CCITY%26Sukor%C3%B3%7CCITY%26K%C3%A1poln%C3%A1sny%C3%A9k%7CCITY&altipus=csaladihaz%7Csorhaz%7Cikerhaz&rendezes=datum-szerint-csokkeno&oldal=1"
DH_URL = "https://dh.hu/elado-ingatlan/haz/gardony+fejer-megye/gardony-agard+velence+gardony+sukoro+pakozd+kapolnasnyek/-/60-93-mFt/80-m2-tol/otthon-start"
ZENGA_URL = "https://www.zenga.hu/velence+agard+gardony+pakozd+sukoro+kapolnasnyek+elado+haz+ar-60000000-93000000+alapterulet-80-+fix3-1"
INGATLAN_URL = "https://ingatlan.com/lista/elado+haz+80-m2-felett+nem-berleti-jog+csaladi-haz+ikerhaz+sorhaz+konnyuszerkezetes-haz+60-93-mFt+velencei-to-kornyeke+fix-3-szazalek"

ENGEDELYEZETT_TELEPULESEK = [
    "velence", "gárdony", "gardony", "agárd", "agard",
    "sukoró", "sukoro", "pákozd", "pakozd",
    "kápolnásnyék", "kapolnasnyek", "nadap"
]

def send_telegram_message(szoveg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": szoveg,
        "parse_mode": "HTML"
    }
    requests.post(url, json=payload)

# --- A TOVÁBBFEJLESZTETT UJJLENYOMAT GENERÁLÓ ---
def keszit_ujjlenyomat(eredeti_id, szoveg, link=""):
    """Megkeresi a várost, árat és méretet, és ebből csinál egyedi azonosítót"""
    ar_szam = 0
    meret_szam = 0
    
    ar_match_millios = re.search(r'([0-9\,\.]+)\s*(?:M|millió)\s*Ft', szoveg, re.IGNORECASE)
    ar_match_sima = re.search(r'([0-9\s\.]+)\s*Ft', szoveg)

    if ar_match_millios:
        ar_tiszta = ar_match_millios.group(1).replace(",", ".")
        try:
            ar_szam = int(float(ar_tiszta) * 1000000)
        except ValueError:
            pass
    elif ar_match_sima:
        ar_tiszta = ar_match_sima.group(1).replace(" ", "").replace(".", "")
        if ar_tiszta.isdigit():
            ar_szam = int(ar_tiszta)

    meret_match = re.search(r'([0-9]+)\s*(?:m2|m²|nm)', szoveg, re.IGNORECASE)
    if meret_match:
        meret_szam = int(meret_match.group(1))

    # --- Város megkeresése ---
    talalt_varos = "ismeretlen"
    ellenorizendo = (szoveg + " " + link).lower()
    
    # Hogy egységes legyen, mindent ékezet nélküli formára hozunk
    varos_szotar = {
        "velence": "velence", "gárdony": "gardony", "gardony": "gardony",
        "agárd": "agard", "agard": "agard", "sukoró": "sukoro", "sukoro": "sukoro",
        "pákozd": "pakozd", "pakozd": "pakozd", "kápolnásnyék": "kapolnasnyek", 
        "kapolnasnyek": "kapolnasnyek", "nadap": "nadap"
    }
    
    for kulcs, tiszta_nev in varos_szotar.items():
        if kulcs in ellenorizendo:
            talalt_varos = tiszta_nev
            break

    # Ha megvan a pontos ár és méret, csinálunk belőle egy univerzális azonosítót a várossal!
    if ar_szam > 0 and meret_szam > 0:
        return f"haz_{talalt_varos}_{ar_szam}_{meret_szam}"
    
    return eredeti_id
# ------------------------------------------------

def scrape_jofogas():
    print("Jófogás letöltése...")
    fejlec = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    valasz = requests.get(JOFOGAS_URL, headers=fejlec)
    if valasz.status_code != 200: return []

    soup = BeautifulSoup(valasz.text, 'html.parser')
    talalatok = []
    
    for doboz in soup.find_all('a', href=True):
        link = doboz['href']
        if "ingatlan.jofogas.hu/" in link and ".htm" in link:
            cim = doboz.text.strip()
            if len(cim) < 5: continue
                
            ellenorizendo_szoveg = (cim + " " + link).lower()
            if not any(telepules in ellenorizendo_szoveg for telepules in ENGEDELYEZETT_TELEPULESEK):
                continue

            alap_id = "jf_" + link.split('/')[-1].split('.')[0]
            szoveg = doboz.get_text(separator=" ", strip=True)
            # Ujjlenyomat generálása linkkel együtt
            vegleges_id = keszit_ujjlenyomat(alap_id, szoveg, link)
            
            if not any(t['id'] == vegleges_id for t in talalatok):
                talalatok.append({"id": vegleges_id, "cim": cim, "link": link, "forras": "Jófogás"})
    return talalatok

def scrape_otp():
    print("OTP IP letöltése (Playwright)...")
    talalatok = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(OTP_URL)
            page.wait_for_timeout(3000) 
            soup = BeautifulSoup(page.content(), 'html.parser')
            
            for doboz in soup.find_all('a', href=True):
                link = doboz.get('href', '')
                if '/ingatlan/M' in link:
                    teljes_link = "https://www.otpip.hu" + link if link.startswith("/") else link
                    hirdetes_id_match = re.search(r'/(M\d+)', link)
                    if not hirdetes_id_match: continue
                    
                    szulo = doboz
                    while len(szulo.get_text(separator=" ", strip=True)) < 30 and szulo.parent:
                        szulo = szulo.parent
                    
                    szoveg = szulo.get_text(separator=" ", strip=True).replace('\xa0', ' ')
                    
                    alap_id = "otp_" + hirdetes_id_match.group(1)
                    vegleges_id = keszit_ujjlenyomat(alap_id, szoveg, teljes_link)

                    # Az OTP kódja alkalmazkodott az új ujjlenyomathoz (benne van a város is)
                    ar_szam, meret_szam = 0, 0
                    if "haz_" in vegleges_id:
                        reszek = vegleges_id.split('_') # pl: ['haz', 'velence', '65000000', '90']
                        ar_szam, meret_szam = int(reszek[2]), int(reszek[3])

                    if (60000000 <= ar_szam <= 93000000) and (meret_szam >= 80):
                        if not any(t['id'] == vegleges_id for t in talalatok):
                            talalatok.append({"id": vegleges_id, "cim": f"OTP Ház ({meret_szam} m², {ar_szam // 1000000} M Ft)", "link": teljes_link, "forras": "OTP Ingatlanpont"})
        except Exception as e: print(e)
        finally: browser.close()
    return talalatok

def scrape_dh():
    print("Duna House letöltése (Playwright)...")
    talalatok = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(DH_URL)
            page.wait_for_timeout(3000) 
            soup = BeautifulSoup(page.content(), 'html.parser')
            
            for doboz in soup.find_all('a', href=True):
                link = doboz.get('href', '')
                id_match = re.search(r'/ingatlan/([A-Za-z]{2}\d+)', link)
                if id_match:
                    alap_id = "dh_" + id_match.group(1).upper()
                    szoveg = doboz.get_text(separator=" ", strip=True)
                    teljes_link = "https://dh.hu" + link if link.startswith("/") else link
                    
                    vegleges_id = keszit_ujjlenyomat(alap_id, szoveg, teljes_link)
                    
                    if not any(t['id'] == vegleges_id for t in talalatok):
                        talalatok.append({"id": vegleges_id, "cim": f"Duna House Ház ({id_match.group(1).upper()})", "link": teljes_link, "forras": "Duna House"})
        except Exception as e: print(e)
        finally: browser.close()
    return talalatok

def scrape_zenga():
    print("Zenga letöltése (Playwright)...")
    talalatok = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(ZENGA_URL)
            page.wait_for_timeout(4000) 
            soup = BeautifulSoup(page.content(), 'html.parser')
            
            for doboz in soup.find_all('a', href=True):
                link = doboz.get('href', '')
                # SZIGORÍTÁS: Csak a valódi ingatlan adatlapokat engedjük be!
                if '/ingatlan/' in link and 'elado' in link and 'haz' in link:
                    teljes_link = "https://www.zenga.hu" + link if link.startswith("/") else link
                    tiszta_link = teljes_link.split('?')[0]
                    id_match = re.search(r'-(\d+)$', tiszta_link)
                    alap_id = "zenga_" + (id_match.group(1) if id_match else re.sub(r'[^a-zA-Z0-9]', '', tiszta_link[-15:]))
                    
                    szoveg = doboz.get_text(separator=" ", strip=True)
                    vegleges_id = keszit_ujjlenyomat(alap_id, szoveg, tiszta_link)
                    
                    if not any(t['id'] == vegleges_id for t in talalatok):
                        cim_szoveg = szoveg[:40] + "..." if len(szoveg) > 40 else "Zenga Ház"
                        talalatok.append({"id": vegleges_id, "cim": cim_szoveg, "link": tiszta_link, "forras": "Zenga"})
        except Exception as e: print(e)
        finally: browser.close()
    return talalatok

def scrape_ingatlan_com():
    print("Ingatlan.com letöltése (Playwright)...")
    talalatok = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        try:
            page = context.new_page()
            page.goto(INGATLAN_URL)
            page.wait_for_timeout(5000) 
            soup = BeautifulSoup(page.content(), 'html.parser')
            
            for doboz in soup.find_all('a', href=True):
                link = doboz.get('href', '')
                tiszta_link = link.split('?')[0]
                id_match = re.search(r'^/(\d{7,9})$', tiszta_link)
                if id_match:
                    alap_id = "icom_" + id_match.group(1)
                    szoveg = doboz.get_text(separator=" ", strip=True)
                    
                    # SZEMÉTKIVETŐ: Kitöröljük a rejtett gomb zavaró szövegét
                    szoveg = szoveg.replace("Elrejtetted ezt az ingatlant és az összes hozzá tartozó hirdetést", "").strip()
                    szoveg = szoveg.replace("Elrejtett ingatlan Mutasd", "").strip()

                    vegleges_id = keszit_ujjlenyomat(alap_id, szoveg, teljes_link)
                    teljes_link = "https://ingatlan.com" + tiszta_link
                    
                    if not any(t['id'] == vegleges_id for t in talalatok):
                        cim_szoveg = szoveg[:50] + "..." if len(szoveg) > 50 else "Ingatlan.com Ház"
                        talalatok.append({"id": vegleges_id, "cim": cim_szoveg, "link": teljes_link, "forras": "Ingatlan.com"})
        except Exception as e: print(e)
        finally: browser.close()
    return talalatok

def main():
    lato_fajl = "lathato.json"
    if os.path.exists(lato_fajl):
        with open(lato_fajl, "r", encoding="utf-8") as f:
            latott_idk = json.load(f)
    else:
        latott_idk = []

    uj_hazak = []
    uj_hazak.extend(scrape_jofogas())
    uj_hazak.extend(scrape_otp())
    uj_hazak.extend(scrape_dh())
    uj_hazak.extend(scrape_zenga())
    uj_hazak.extend(scrape_ingatlan_com())

    uj_talalat_szam = 0
    csv_fajl = "adatbazis.csv"
    csv_letezik = os.path.exists(csv_fajl)

    for haz in uj_hazak:
        if haz["id"] not in latott_idk:
            uj_talalat_szam += 1
            forras = haz.get("forras", "Ismeretlen portál")
            
            # --- 1. TELEGRAM ÜZENET KÜLDÉSE ---
            uzenet = f"🏠 <b>Új ház: {forras}</b>\n\n<b>Cím:</b> {haz['cim']}\n🔗 <a href='{haz['link']}'>Kattints ide a hirdetésért</a>"
            send_telegram_message(uzenet)
            
            # VÁRUNK 2 MÁSODPERCET, HOGY A TELEGRAM NE TILTSA LE A BOTOT SPAMELÉSÉRT!
            time.sleep(2)
            
            # --- 2. MENTÉS A CSV TÁBLÁZATBA ---
            with open(csv_fajl, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not csv_letezik:
                    # Ha még sose volt ilyen fájl, csinálunk neki egy szép fejlécet
                    writer.writerow(["Dátum", "Forrás", "Cím", "Link", "Azonosító"])
                    csv_letezik = True
                
                # Bepakoljuk a friss házat a táblázat végére
                mai_datum = datetime.now().strftime("%Y-%m-%d %H:%M")
                writer.writerow([mai_datum, forras, haz['cim'], haz['link'], haz['id']])

            # --- 3. MEMÓRIA FRISSÍTÉSE ---
            latott_idk.append(haz["id"]) 

    if uj_talalat_szam > 0:
        with open(lato_fajl, "w", encoding="utf-8") as f:
            json.dump(latott_idk, f)
        print(f"✅ {uj_talalat_szam} db új hirdetés elküldve a Telegramra és mentve a CSV-be!")
    else:
        print("💤 Nincs új hirdetés, a bot csendben marad.")

if __name__ == "__main__":
    main()
