#!/usr/bin/env python3

import copy
import gzip
import sys
import urllib.request
import xml.etree.ElementTree as ET

from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
#SOURCES_FILE = BASE_DIR / "sources.txt"
OUTPUT_FILE = BASE_DIR / "epg_merged.xml"
SOURCES_FILE = Path("/media/kodi/epg/sources.txt")
#RULES_FILE = Path("/media/kodi/epg/rules.json")
#OUTPUT_FILE = Path("/media/kodi/epg/epg_merged.xml")

TIMEOUT = 120

# Elementy, dla których zachowujemy jedną wartość
# na dany język, zgodnie z priorytetem źródeł.
SINGLETON_TAGS = {
    "title",
    "sub-title",
    "desc",
    "date",
    "length",
    "episode-num",
    "url",
    "premiere",
    "last-chance",
    "previously-shown",
    "new",
    "icon",
}

# Kontenery zawierające dalsze elementy XML.
CONTAINER_TAGS = {
    "credits",
    "rating",
    "star-rating",
    "video",
    "audio",
    "review",
}


def local_tag(element):
    """Nazwa elementu bez ewentualnej przestrzeni nazw."""
    return element.tag.split("}")[-1]


def normalized_text(element):
    return " ".join("".join(element.itertext()).split())


def get_language(element):
    return element.get("lang", "")


def get_match_key(element):
    """
    Określa, czy element z drugiego źródła odpowiada
    elementowi, który już znajduje się w dokumencie.
    """
    tag = local_tag(element)
    lang = get_language(element)

    if tag == "icon":
        # Ikony o różnych adresach mogą współistnieć.
        return tag, element.get("src", "")

    if tag == "display-name":
        # Nazwa w języku polskim uzupełnia nazwę polską,
        # a nie np. angielską.
        return tag, lang

    if tag in SINGLETON_TAGS:
        return tag, lang

    if tag in CONTAINER_TAGS:
        return tag, lang

    # Elementy powtarzalne, np. category, keyword,
    # country, actor czy director.
    return tag, lang, normalized_text(element)


def merge_element(target, source):
    """
    Uzupełnia target danymi ze source.
    Istniejące wartości mają pierwszeństwo.
    Brakujące elementy i podelementy są dodawane.
    """
    # Uzupełnij brakujące atrybuty.
    for key, value in source.attrib.items():
        if not target.get(key):
            target.set(key, value)

    # Uzupełnij tekst tylko wtedy, gdy go brakuje.
    if not normalized_text(target) and normalized_text(source):
        target.text = source.text

    existing = {}

    for child in target:
        key = get_match_key(child)
        existing.setdefault(key, []).append(child)

    for source_child in source:
        key = get_match_key(source_child)
        candidates = existing.get(key, [])

        if candidates:
            # Dla pól pojedynczych dopasowanie jest jednoznaczne.
            # Dla pól powtarzalnych łączymy tylko identyczne wpisy.
            merge_element(candidates[0], source_child)
        else:
            new_child = copy.deepcopy(source_child)
            target.append(new_child)
            existing.setdefault(key, []).append(new_child)


def read_source(source):
    """Odczytuje lokalny plik albo pobiera źródło HTTP/HTTPS."""
    source = source.strip()

    if source.startswith(("http://", "https://")):
        request = urllib.request.Request(
            source,
            headers={"User-Agent": "Kodi/21.2 (Windows NT 10.0.19045.7807; Win64; x64) App_Bitness/64 Version/21.2-(21.2.0)-Git:20250115-d1a1d48c3c"},
#            headers={"User-Agent": "EPG-Merger/1.0"},
        )

        with urllib.request.urlopen(
            request, timeout=TIMEOUT
        ) as response:
            data = response.read()
    else:
        path = Path(source)

        if not path.is_absolute():
            path = BASE_DIR / path

        data = path.read_bytes()

    # Obsługa GZIP również wtedy, gdy plik nie ma rozszerzenia .gz.
    if data.startswith(b"\x1f\x8b"):
        data = gzip.decompress(data)

    return data


def source_name(source):
    if source.startswith(("http://", "https://")):
        return urlparse(source).netloc
    return source


def load_sources():
    if not SOURCES_FILE.is_file():
        raise FileNotFoundError(
            f"Nie znaleziono konfiguracji: {SOURCES_FILE}"
        )

    sources = []

    for line in SOURCES_FILE.read_text(
        encoding="utf-8-sig"
    ).splitlines():
        line = line.strip()

        if line and not line.startswith("#"):
            sources.append(line)

    if not sources:
        raise ValueError("Brak źródeł w sources.txt")

    return sources


def merge_epg():
    sources = load_sources()

    root = None
    channels = {}
    programmes = {}

    successful = 0
    failed = 0

    for source in sources:
        print(f"[EPG] Wczytywanie: {source_name(source)}")

        try:
            data = read_source(source)
            source_root = ET.fromstring(data)

            if local_tag(source_root) != "tv":
                raise ValueError("Głównym elementem XML nie jest <tv>")

        except Exception as exc:
            failed += 1
            print(f"[BŁĄD] {source_name(source)}: {exc}")
            continue

        successful += 1

        if root is None:
            root = ET.Element("tv", source_root.attrib)

        else:
            # Uzupełnij brakujące atrybuty głównego elementu.
            for key, value in source_root.attrib.items():
                if not root.get(key):
                    root.set(key, value)

        for element in source_root:
            tag = local_tag(element)

            if tag == "channel":
                channel_id = element.get("id")

                if not channel_id:
                    print("[UWAGA] Pominięto kanał bez id")
                    continue

                if channel_id in channels:
                    merge_element(channels[channel_id], element)
                else:
                    new_element = copy.deepcopy(element)
                    root.append(new_element)
                    channels[channel_id] = new_element

            elif tag == "programme":
                channel_id = element.get("channel")
                start = element.get("start")
                stop = element.get("stop")

                # Klucz programu: kanał, start i koniec.
                key = (channel_id, start, stop)

                if key in programmes:
                    merge_element(programmes[key], element)
                else:
                    new_element = copy.deepcopy(element)
                    root.append(new_element)
                    programmes[key] = new_element

            else:
                # Zachowaj także inne elementy XMLTV.
                root.append(copy.deepcopy(element))

        print(
            f"[OK] Kanały: {len(channels)}, "
            f"unikalne programy: {len(programmes)}"
        )

    if root is None:
        raise RuntimeError(
            "Nie udało się wczytać żadnego poprawnego źródła EPG."
        )

    # Standardowa kolejność: kanały, programy, pozostałe elementy.
    channel_elements = [
        el for el in root if local_tag(el) == "channel"
    ]
    programme_elements = [
        el for el in root if local_tag(el) == "programme"
    ]
    other_elements = [
        el for el in root
        if local_tag(el) not in ("channel", "programme")
    ]

    root[:] = (
        channel_elements
        + programme_elements
        + other_elements
    )

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")

    temp_file = OUTPUT_FILE.with_suffix(".xml.tmp")

    try:
        tree.write(
            temp_file,
            encoding="utf-8",
            xml_declaration=True,
        )
        temp_file.replace(OUTPUT_FILE)
    except Exception:
        temp_file.unlink(missing_ok=True)
        raise

    print("\n========== PODSUMOWANIE ==========")
    print(f"Źródła w konfiguracji: {len(sources)}")
    print(f"Źródła wczytane:       {successful}")
    print(f"Źródła z błędami:      {failed}")
    print(f"Unikalne kanały:       {len(channels)}")
    print(f"Unikalne programy:     {len(programmes)}")
    print(f"Plik wynikowy:         {OUTPUT_FILE}")


if __name__ == "__main__":
    try:
        merge_epg()
    except Exception as exc:
        print(f"[FATALNY BŁĄD] {exc}", file=sys.stderr)
        sys.exit(1)
