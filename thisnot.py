import cloudscraper
import re
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin
import base64
import json

print("Inizializzazione del client cloudscraper...")
scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})

BASE_URL = "https://www.4nabbi.eu"
PASSWORD = "2025"
EVENTI_URL = f"{BASE_URL}/eventi.php"

# =============================================
# FUNZIONI LOGIN E SUPPORTO
# =============================================

def perform_login(url, pwd):
    print(f"\n🔑 Tentativo di login su {url}")
    try:
        response = scraper.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        form = soup.find('form')
        if form:
            action = form.get('action', '')
            action_url = urljoin(BASE_URL, action) if action else url
            inputs = {inp.get('name'): inp.get('value', '') for inp in form.find_all('input') if inp.get('name')}
        else:
            action_url = url
            inputs = {}
        inputs['password'] = pwd
        login_response = scraper.post(action_url, data=inputs, allow_redirects=True)
        login_response.raise_for_status()
        if "INSERIRE PASSWORD" not in login_response.text.upper():
            print("✅ Login riuscito")
            return True
        print("❌ Password non accettata")
        return False
    except Exception as e:
        print(f"Errore nel login: {e}")
        return False


def get_page_content(url):
    try:
        response = scraper.get(url, allow_redirects=True)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Errore nel caricamento di {url}: {e}")
        return None


def decode_token(token_raw):
    try:
        missing_padding = len(token_raw) % 4
        if missing_padding:
            token_raw += "=" * (4 - missing_padding)
        decoded_bytes = base64.b64decode(token_raw)
        decoded_str = decoded_bytes.decode('utf-8').strip()
        
        key_pairs = []
        tokens_to_process = []

        if decoded_str.startswith('{'):
            try:
                data = json.loads(decoded_str)
                keyid, key = list(data.items())[0]
                tokens_to_process.append(f"{keyid}:{key}")
            except json.JSONDecodeError:
                tokens_to_process.append(decoded_str)
        elif decoded_str.startswith('['):
            try:
                data_list = json.loads(decoded_str)
                for item in data_list:
                    if isinstance(item, dict):
                        keyid, key = list(item.items())[0]
                        tokens_to_process.append(f"{keyid}:{key}")
            except json.JSONDecodeError:
                tokens_to_process.append(decoded_str)
        else:
            tokens_to_process = decoded_str.split(',')

        for token in tokens_to_process:
            token = token.strip()
            if ':' in token:
                keyid, key = token.split(':', 1)
                key_pairs.append((keyid.lower(), key.lower()))

        return key_pairs
    except:
        return []


def estrai_mpd_e_token(iframe_src):
    if "#" in iframe_src:
        real_url = iframe_src.split("#", 1)[1]
    else:
        real_url = iframe_src

    ck_start_a = real_url.find('&ck=')
    ck_start_q = real_url.find('?ck=')

    if ck_start_q != -1 and (ck_start_a == -1 or ck_start_q < ck_start_a):
        start_index = ck_start_q
    elif ck_start_a != -1:
        start_index = ck_start_a
    else:
        return None, None

    mpd_url = real_url[:start_index]
    token_part = real_url[start_index + 4:]

    if '&' in token_part:
        token_raw = token_part.split('&', 1)[0]
    else:
        token_raw = token_part

    return mpd_url, token_raw


# =============================================
# NUOVO PROCESSAMENTO EVENTI
# =============================================

def process_eventi():
    print(f"\n🏆 Caricamento eventi da {EVENTI_URL}")
    html_content = get_page_content(EVENTI_URL)
    if not html_content:
        print("❌ Impossibile caricare eventi")
        return

    soup = BeautifulSoup(html_content, 'html.parser')
    m3u8_content = "#EXTM3U\n"
    seen_entries = set()
    total = 0

    all_sections = soup.find_all("h2")

    for section in all_sections:
        comp_name = section.get_text(strip=True)

        table = section.find_next("table")
        if not table:
            continue

        rows = table.find_all("tr")[1:]  # salto header

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 4:
                continue

            ora = cols[0].get_text(strip=True)
            competizione = cols[1].get_text(strip=True)
            match = cols[2].get_text(strip=True)
            link_tag = cols[3].find("a")

            if not link_tag:
                continue

            player_url = urljoin(BASE_URL, link_tag.get("href"))

            print(f"\n⚽ {match} {ora} | {competizione}")

            player_page = get_page_content(player_url)
            if not player_page:
                continue

            iframe_match = re.search(r'<iframe[^>]*src=["\']([^"\']+)["\']',
                                     player_page, re.IGNORECASE)
            if not iframe_match:
                print("❌ Nessun iframe")
                continue

            iframe_src = iframe_match.group(1)

            if "nochannel" in iframe_src:
                print("⚠️ Nessun canale per questo evento")
                continue

            mpd_url, raw_token = estrai_mpd_e_token(iframe_src)
            if not mpd_url or not raw_token:
                print("❌ MPD o token non trovati")
                continue

            key_pairs = decode_token(raw_token)
            if not key_pairs:
                print("❌ Nessuna chiave valida")
                continue

            event_title = f"{match} {ora}"

            for idx, (kid, key) in enumerate(key_pairs):
                suffix = f" (Key {idx + 1})" if len(key_pairs) > 1 else ""
                final_title = event_title + suffix

                entry_key = (final_title, mpd_url, kid, key)
                if entry_key in seen_entries:
                    continue
                seen_entries.add(entry_key)

                # Aggiunta al file M3U8
                m3u8_content += f'#EXTINF:-1 tvg-logo="https://techprincess.it/wp-content/uploads/2022/08/dazn-sky.jpg.webp" group-title="{competizione}",{final_title}\n'
                m3u8_content += "#KODIPROP:inputstream.adaptive.license_type=clearkey\n"
                m3u8_content += f"#KODIPROP:inputstream.adaptive.license_key={kid}:{key}\n"
                m3u8_content += f"{mpd_url}\n\n"

                total += 1

    # SALVATAGGIO FINALE
    out_path = os.path.join(os.getcwd(), "thisnot.m3u8")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(m3u8_content)

    print(f"\n✅ File generato: {out_path}")
    print(f"📌 Eventi trovati: {total}")


# =============================================
# ESECUZIONE PRINCIPALE
# =============================================

if not perform_login(f"{BASE_URL}/eventi.php", PASSWORD):
    print("❌ Login fallito. Interrompo.")
    exit()

process_eventi()

print("\n🎉 Tutto completato con successo!")
