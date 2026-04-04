import requests
import json
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# --- BEÁLLÍTÁSOK ---
import os
from dotenv import load_dotenv

# Betöltjük a titkos adatokat a .env fájlból a "színfalak mögött"
load_dotenv()

# --- BEÁLLÍTÁSOK ---
# A kód innentől az operációs rendszertől kéri el a kulcsokat, nem a kódból olvassa!
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")



JOFOGAS_URL = "https://ingatlan.jofogas.hu/fejer/haz?max_price=93000000&min_size=80&st=s"
ENGEDELYEZETT_TELEPULESEK = [
    "velence", "gárdony", "gardony", "agárd", "agard",
    "sukoró", "sukoro", "pákozd", "pakozd",
    "kápolnásnyék", "kapolnasnyek", "nadap"
]

OTP_URL = "https://www.otpip.hu/kereses?ertekesitestipusa=elado&ingatlantipusa=haz&allapot=uj-epitesu&elhelyezkedes=Velence%7CCITY%26G%C3%A1rdony%7CCITY%26P%C3%A1kozd%7CCITY%26Sukor%C3%B3%7CCITY%26K%C3%A1poln%C3%A1sny%C3%A9k%7CCITY&altipus=csaladihaz%7Csorhaz%7Cikerhaz&rendezes=datum-szerint-csokkeno&oldal=1"

DH_URL = "https://dh.hu/elado-ingatlan/haz/gardony+fejer-megye/gardony-agard+velence+gardony+sukoro+pakozd+kapolnasnyek/-/60-93-mFt/80-m2-tol/otthon-start"

ZENGA_URL = "https://www.zenga.hu/velence+agard+gardony+pakozd+sukoro+kapolnasnyek+elado+haz+ar-60000000-93000000+alapterulet-80-+fix3-1"

INGATLAN_URL = "https://ingatlan.com/lista/elado+haz+80-m2-felett+nem-berleti-jog+csaladi-haz+ikerhaz+sorhaz+konnyuszerkezetes-haz+60-93-mFt+velencei-to-kornyeke+fix-3-szazalek"

def send_telegram_message(szoveg):
    """Elküldi az üzenetet a Telegramra HTML formázással"""
    url = f"https://api.telegram.org/bot8221850739:AAHOsgxp6NdaDPE0XO9WBHChP2oZHiukirs/sendMessage"
    payload = {
        "chat_id": 8709971523,
        "text": szoveg,
        "parse_mode": "HTML"
    }
    requests.post(url, json=payload)


def scrape_jofogas():
    """Lekéri és szűri a Jófogás hirdetéseit"""
    fejlec = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    valasz = requests.get(JOFOGAS_URL, headers=fejlec)

    if valasz.status_code != 200:
        print(f"Hiba a Jófogás letöltésekor: {valasz.status_code}")
        return []

    soup = BeautifulSoup(valasz.text, 'html.parser')
    talalatok = []
    hirdetes_dobozok = soup.find_all('a', href=True)

    for doboz in hirdetes_dobozok:
        link = doboz['href']
        if "ingatlan.jofogas.hu/" in link and ".htm" in link:
            cim = doboz.text.strip()
            if len(cim) < 5:
                continue

            ellenorizendo_szoveg = (cim + " " + link).lower()
            jo_helyen_van = any(telepules in ellenorizendo_szoveg for telepules in ENGEDELYEZETT_TELEPULESEK)

            if not jo_helyen_van:
                continue

            hirdetes_id = link.split('/')[-1].split('.')[0]
            ha_mar_benne_van = any(t['id'] == hirdetes_id for t in talalatok)

            if not ha_mar_benne_van:
                talalatok.append({
                    "id": hirdetes_id,
                    "cim": cim,
                    "link": link
                })
    return talalatok


def scrape_otp():
    print("OTP IP letöltése (Playwright böngészővel)...")
    talalatok = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto(OTP_URL)
            page.wait_for_timeout(3000)

            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')

            hirdetes_dobozok = soup.find_all('a', href=True)

            for doboz in hirdetes_dobozok:
                link = doboz.get('href', '')

                # Csak a konkrét ingatlan hirdetéseket nézzük az "M" azonosító alapján
                if '/ingatlan/M' in link:
                    teljes_link = "https://www.otpip.hu" + link if link.startswith("/") else link

                    # Kinyerjük az egyedi azonosítót, pl. M319289
                    hirdetes_id_match = re.search(r'/(M\d+)', link)
                    if not hirdetes_id_match:
                        continue
                    hirdetes_id = hirdetes_id_match.group(1)

                    # --- A TRÜKK: Szöveg kinyerése a kártyáról ---
                    # Ha az <a> tagben nincs elég szöveg, feljebb megyünk a szülő HTML elemekhez
                    szulo = doboz
                    # A get_text(separator=" ") gondoskodik róla, hogy a szavak ne csússzanak egybe!
                    while len(szulo.get_text(separator=" ", strip=True)) < 30 and szulo.parent:
                        szulo = szulo.parent

                    szoveg = szulo.get_text(separator=" ", strip=True).replace('\xa0', ' ')

                    # --- ÁR ÉS MÉRET SZŰRŐ ---
                    ar_szam = 0
                    meret_szam = 0

                    # Keresünk milliós (pl. 85,5 M Ft) és sima (85 000 000 Ft) formátumokat is
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

                    # --- A VÉGSŐ DÖNTÉS ---
                    # Csak akkor engedjük tovább, ha bekerül a sávba!
                    if (60000000 <= ar_szam <= 93000000) and (meret_szam >= 80):
                        ha_mar_benne_van = any(t['id'] == hirdetes_id for t in talalatok)
                        if not ha_mar_benne_van:
                            talalatok.append({
                                "id": "otp_" + hirdetes_id,
                                "cim": f"OTP Ház ({meret_szam} m², {ar_szam // 1000000} M Ft)",
                                "link": teljes_link
                            })

        except Exception as e:
            print(f"Hiba a Playwright futása közben: {e}")
        finally:
            browser.close()

    return talalatok


def scrape_dh():
    print("Duna House letöltése (Playwright böngészővel)...")
    talalatok = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto(DH_URL)
            page.wait_for_timeout(3000)

            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')

            hirdetes_dobozok = soup.find_all('a', href=True)

            for doboz in hirdetes_dobozok:
                link = doboz.get('href', '')

                # A DH hirdetések általában így néznek ki: /ingatlan/HZ123456
                # Ezzel a regex-el megkeressük azokat a linkeket, amikben 2 betű és utána számok vannak
                id_match = re.search(r'/ingatlan/([A-Za-z]{2}\d+)', link)

                if id_match:
                    hirdetes_id = id_match.group(1).upper()
                    teljes_link = "https://dh.hu" + link if link.startswith("/") else link

                    ha_mar_benne_van = any(t['id'] == "dh_" + hirdetes_id for t in talalatok)

                    if not ha_mar_benne_van:
                        talalatok.append({
                            "id": "dh_" + hirdetes_id,
                            "cim": f"Duna House Ház ({hirdetes_id})",
                            "link": teljes_link
                        })

        except Exception as e:
            print(f"Hiba a Duna House futása közben: {e}")
        finally:
            browser.close()

    return talalatok


def scrape_zenga():
    print("Zenga letöltése (Playwright böngészővel)...")
    talalatok = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto(ZENGA_URL)
            page.wait_for_timeout(4000)  # A Zenga betöltése néha picit lassabb, adunk neki 4 másodpercet

            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')

            hirdetes_dobozok = soup.find_all('a', href=True)

            for doboz in hirdetes_dobozok:
                link = doboz.get('href', '')

                # Kiszűrjük a releváns ingatlan linkeket a menüből
                if 'elado' in link and 'haz' in link and 'kereses' not in link and len(link) > 25:
                    teljes_link = "https://www.zenga.hu" + link if link.startswith("/") else link
                    tiszta_link = teljes_link.split('?')[0]  # Levágjuk a "követőkódokat" a link végéről

                    # Megpróbáljuk kinyerni az azonosítót a link végéből (pl. -1234567)
                    id_match = re.search(r'-(\d+)$', tiszta_link)
                    if id_match:
                        hirdetes_id = id_match.group(1)
                    else:
                        # Ha nincs szám, használjuk a link végét azonosítónak
                        hirdetes_id = re.sub(r'[^a-zA-Z0-9]', '', tiszta_link[-15:])

                    ha_mar_benne_van = any(t['id'] == "zenga_" + hirdetes_id for t in talalatok)

                    if not ha_mar_benne_van:
                        # Ha a kártyán van szöveg, abból csinálunk címet
                        cim_szoveg = doboz.get_text(separator=" ", strip=True)
                        rovid_cim = cim_szoveg[:40] + "..." if len(cim_szoveg) > 40 else "Zenga Ház"
                        if len(rovid_cim) < 5:
                            rovid_cim = "Zenga Ház"

                        talalatok.append({
                            "id": "zenga_" + hirdetes_id,
                            "cim": rovid_cim,
                            "link": tiszta_link
                        })

        except Exception as e:
            print(f"Hiba a Zenga futása közben: {e}")
        finally:
            browser.close()

    return talalatok


def scrape_ingatlan_com():
    print("Ingatlan.com letöltése (Playwright böngészővel)...")
    talalatok = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Egy kis extra álcázás: megmondjuk neki, hogy ez egy Windows 10-es Chrome böngésző
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            page.goto(INGATLAN_URL)
            # Adunk neki 5 másodpercet, ha esetleg a Cloudflare "ellenőrzi a böngésződet"
            page.wait_for_timeout(5000)

            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')

            hirdetes_dobozok = soup.find_all('a', href=True)

            for doboz in hirdetes_dobozok:
                link = doboz.get('href', '')
                tiszta_link = link.split('?')[0]  # Levágjuk a felesleget

                # Az ingatlan.com hirdetés linkjei így néznek ki: /12345678
                id_match = re.search(r'^/(\d{7,9})$', tiszta_link)

                if id_match:
                    hirdetes_id = id_match.group(1)
                    teljes_link = "https://ingatlan.com" + tiszta_link

                    ha_mar_benne_van = any(t['id'] == "icom_" + hirdetes_id for t in talalatok)

                    if not ha_mar_benne_van:
                        # Próbálunk valami értelmes címet kinyerni
                        cim_szoveg = doboz.get_text(separator=" ", strip=True)
                        rovid_cim = cim_szoveg[:50] + "..." if len(cim_szoveg) > 50 else cim_szoveg
                        if len(rovid_cim) < 5:
                            rovid_cim = f"Ingatlan.com Ház ({hirdetes_id})"

                        talalatok.append({
                            "id": "icom_" + hirdetes_id,
                            "cim": rovid_cim,
                            "link": teljes_link
                        })

        except Exception as e:
            print(f"Hiba az Ingatlan.com futása közben: {e}")
        finally:
            browser.close()

    return talalatok


def main():
    lato_fajl = "lathato.json"
    if os.path.exists(lato_fajl):
        with open(lato_fajl, "r", encoding="utf-8") as f:
            latott_idk = json.load(f)
    else:
        latott_idk = []

    print("Jófogás ellenőrzése...")
    uj_hazak = scrape_jofogas()
    print("OTP Ingatlanpont ellenőrzése...")
    uj_hazak.extend(scrape_otp())
    print("Duna House ellenőrzése...")
    uj_hazak.extend(scrape_dh())
    print("Zenga ellenőrzése...")
    uj_hazak.extend(scrape_zenga())
    print("Ingatlan.com ellenőrzése...")
    uj_hazak.extend(scrape_ingatlan_com())


    uj_talalat_szam = 0

    for haz in uj_hazak:
        if haz["id"] not in latott_idk:
            uj_talalat_szam += 1

            # Dinamikus forrás meghatározás az ID eleje alapján
            if "otp_" in haz["id"]:
                forras = "OTP Ingatlanpont"
            elif "dh_" in haz["id"]:
                forras = "Duna House"
            elif "zenga_" in haz["id"]:
                forras = "Zenga"
            elif "icom_" in haz["id"]:
                forras = "Ingatlan.com"
            else:
                forras = "Jófogás"

            uzenet = f"🏠 <b>Új ház: {forras}</b>\n\n<b>Cím:</b> {haz['cim']}\n🔗 <a href='{haz['link']}'>Kattints ide a hirdetésért</a>"

            send_telegram_message(uzenet)
            latott_idk.append(haz["id"])

    if uj_talalat_szam > 0:
        with open(lato_fajl, "w", encoding="utf-8") as f:
            json.dump(latott_idk, f)
        print(f"✅ {uj_talalat_szam} db új hirdetés elküldve a telefonodra!")
    else:
        print("💤 Nincs új hirdetés, a bot csendben marad.")


if __name__ == "__main__":
    main()