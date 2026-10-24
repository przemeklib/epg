#!/usr/bin/env python3
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import sys
import urllib.parse
import os
import gzip
from pathlib import Path

# --- KONFIGURACJA ---
#URL = "https://epg.ovh/pltv.gz"
BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "epg_merged.xml"
OUTPUT_FILE = "/media/kodi/epg.xml"

REMOVE_LIST_FILE = "/media/kodi/remove_channels.txt"
ORDER_LIST_FILE = "/media/kodi/order_channels.txt"

RESIZER_URL = "https://twójserwer/thumb.php"   # nie zapomnij nadać uprawnień do folderu cache jeśli zmieniasz rozmiary więcej w pliku thumb
THUMB_WIDTH = 380
LOGO_HEIGHT = 120
DAYS_FORWARD = 0
END_HOUR = 6
PAST_BUFFER_HOURS = 5
# --------------------

def parse_xmltv_date(date_str):
    try:
        return datetime.strptime(date_str, '%Y%m%d%H%M%S %z')
    except:
        return None
"""
def download_epg(url):
    print(f"Pobieranie EPG z {url}...")
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        print(f"Pobrano {len(r.content)} bajtow.")
        
        if url.endswith('.gz'):
            print("Rozpakowywanie pliku GZ w pamięci...")
            content = gzip.decompress(r.content)
            print(f"Rozpakowano. Rozmiar po dekompresji: {len(content)} bajtow.")
            return content
            
        return r.content
    except Exception as e:
        print(f"Blad pobierania lub dekompresji: {e}")
        sys.exit(1)
"""
def load_epg(filepath):
    print(f"Wczytywanie EPG z pliku {filepath}...")

    try:
        with open(filepath, "rb") as f:
            content = f.read()

        print(f"Wczytano {len(content)} bajtów.")

        # Rozpoznajemy GZIP po sygnaturze pliku,
        # a nie tylko po rozszerzeniu .gz.
        if content.startswith(b"\x1f\x8b"):
            print("Rozpakowywanie pliku GZIP w pamięci...")
            content = gzip.decompress(content)
            print(
                f"Rozpakowano. Rozmiar XML: "
                f"{len(content)} bajtów."
            )

        return content

    except Exception as e:
        print(f"Błąd odczytu lub dekompresji pliku: {e}")
        sys.exit(1)


def load_blocked_channels(filepath):
    blocked = set()
    if not os.path.exists(filepath):
        print(f"UWAGA: Plik {filepath} nie istnieje. Pomijam filtrowanie.")
        return blocked

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                # Czysty tekst: bez komentarzy, bez białych znaków, małe litery
                line = line.split('#')[0].strip().lower()
                if line:
                    blocked.add(line)
        print(f"Wczytano {len(blocked)} kanałów do usunięcia.")
    except Exception as e:
        print(f"Błąd odczytu pliku: {e}")

    return blocked

def load_channel_order(filepath):
    order = []
    if not os.path.exists(filepath):
        print(f"UWAGA: Plik {filepath} nie istnieje. Pomijam sortowanie.")
        return order

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                # Czysty tekst: bez komentarzy, bez białych znaków, małe litery
                line = line.split('#')[0].strip().lower()
                if line and line not in order:
                    order.append(line)
        print(f"Wczytano {len(order)} kanałów do posortowania.")
    except Exception as e:
        print(f"Błąd odczytu pliku: {e}")

    return order

def filter_and_sort_epg(xml_content, blocked_channels, order_list):
    print("Przetwarzanie XML...")
    root = ET.fromstring(xml_content)
    now = datetime.now(timezone.utc)
    start_cutoff = now - timedelta(hours=PAST_BUFFER_HOURS)
    end_cutoff = (now + timedelta(days=DAYS_FORWARD + 1)).replace(hour=END_HOUR, minute=0, second=0, microsecond=0)

    channels_to_remove = []
    channels_to_keep = []

    # 1. Filtrowanie kanałów
    for channel in root.findall('channel'):
        # Pobieramy ID z XML, usuwamy spacje z brzegów i zamieniamy na małe litery
        c_id = (channel.get('id') or "").strip().lower()

        if c_id in blocked_channels:
            channels_to_remove.append(channel)
            continue

        icon = channel.find('icon')
        if icon is not None:
            src = icon.get('src')
            if src:
                icon.set('src', f"{RESIZER_URL}?h={LOGO_HEIGHT}&src={urllib.parse.quote(src, safe='')}")

        channels_to_keep.append(channel)

    for c in channels_to_remove:
        root.remove(c)
    print(f"Usunięto {len(channels_to_remove)} kanałów (zgodnie z listą blokowanych).")

    # 2. Sortowanie kanałów
    if order_list:
        for c in channels_to_keep:
            root.remove(c)

        def sort_key(channel):
            c_id = (channel.get('id') or "").strip().lower()
            try:
                return order_list.index(c_id)
            except ValueError:
                return len(order_list)

        channels_to_keep.sort(key=sort_key)

        for index, channel in enumerate(channels_to_keep):
            root.insert(index, channel)
        print("Posortowano kanały według własnej listy.")

    # 3. Usuwanie programów
    progs_to_remove = []
    for prog in root.findall('programme'):
        # Uodpornienie ID w tagu programme
        channel_ref = (prog.get('channel') or "").strip().lower()

        if channel_ref in blocked_channels:
            progs_to_remove.append(prog)
            continue

        start = parse_xmltv_date(prog.get('start'))
        if not start or start < start_cutoff or start > end_cutoff:
            progs_to_remove.append(prog)
            continue

        icon = prog.find('icon')
        if icon is not None:
            src = icon.get('src')
            if src:
                icon.set('src', f"{RESIZER_URL}?w={THUMB_WIDTH}&src={urllib.parse.quote(src, safe='')}")

    for p in progs_to_remove:
        root.remove(p)
    print(f"Usunięto łącznie {len(progs_to_remove)} wpisów programowych.")

    return ET.ElementTree(root)

def save_epg(tree, filename):
    print(f"Zapisywanie...")
    xml_str = ET.tostring(tree.getroot(), encoding='UTF-8', xml_declaration=True).decode('UTF-8')
#    fixed_xml = xml_str.replace('&', '&amp;')
    with open(filename, "w", encoding="UTF-8") as f:
#        f.write(fixed_xml)
        f.write(xml_str)
    print(f"Gotowe: {filename}")

if __name__ == "__main__":
#    data = download_epg(URL)
    data = load_epg(INPUT_FILE)
    blocked_list = load_blocked_channels(REMOVE_LIST_FILE)
    order_list = load_channel_order(ORDER_LIST_FILE)
    tree = filter_and_sort_epg(data, blocked_list, order_list)
    save_epg(tree, OUTPUT_FILE)
