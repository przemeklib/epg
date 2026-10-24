#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rakuten TV PL -> XMLTV EPG
Pobiera program bezpłatnych kanałów z polską ścieżką audio.

Wymagania:
    pip install requests

Uruchomienie:
    python3 rakuten_epg.py

Opcjonalnie:
    python3 rakuten_epg.py -o /home/memek/rakuten.xml
    python3 rakuten_epg.py --past 2 --future 12
    python3 rakuten_epg.py --minify
"""

import argparse
import logging
import sys
import time
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


API_URL = "https://gizmo.rakuten.tv/v3/"
BASE_URL = "https://www.rakuten.tv/"

WARSAW_TZ = ZoneInfo("Europe/Warsaw")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; "
        "rv:109.0) Gecko/20100101 Firefox/115.0"
    ),
    "Referer": BASE_URL,
    "Origin": BASE_URL.rstrip("/"),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
}

PARAMS = {
    "classification_id": "277",
    "device_identifier": "web",
    "device_stream_audio_quality": "2.0",
    "device_stream_hdr_type": "NONE",
    "device_stream_video_quality": "FHD",
    "locale": "pl",
    "market_code": "pl",
    "live_channel_support": "true",
    "user_status": "visitor",
}

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = BASE_DIR / "rakuten.xml"
PAGE_SIZE = 50
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3


# Ręczne ustawienia kanałów:
# klucz = nazwa kanału zwrócona przez API,
# id = opcjonalne alternatywne ID XMLTV,
# logo = opcjonalny ręcznie ustawiony adres logo.
CHANNEL_OVERRIDES = {
    "Euronews LIVE": {
        "logo": "https://epg.ovh/logo/Euronews+Polska.png",
    },
    "Viasat Explore Classic": {
        "id": "Viasat Explore Classic zapas",
        "logo": "https://epg.ovh/logo/Viasat+Explore+Classic.png",
    },
    "Moconomy - Gospodarka i Finanse": {
        "logo": "https://epg.ovh/logo/Moconomy.png",
    },
    "Car City Adventures": {
        "logo": "https://epg.ovh/logo/Car+City+Adventures.png",
    },
    "Red Carpet TV International": {
#        "id": "Red Carpet",
        "logo": "https://epg.ovh/logo/Red+Carpet.png",
    },
    "wedotv Auta": {
        "id": "wedotv Auta zapas",
        "logo": "https://epg.ovh/logo/Wedotv+Auta.png",
    },
    "Grjngo - Westerny": {
        "id": "Grjngo zapas",
        "logo": "https://epg.ovh/logo/Grjngo+Westerny.png",
    },
    "Bigtime - Darmowe Filmy": {
        "logo": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRFOMYDAXifaTVa2lmJ9svxjx9LHzOzBzPhBpIrC9SyNg&s=10",
    },
    "Top Movies Polska - Rakuten TV": {
        "logo": "https://epg.ovh/logo/RakutenTV.png",
    },
}


def normalize_channel_name(name):
    """Normalizuje nazwę do dopasowania niezależnego od wielkości liter i spacji."""
    return " ".join(str(name or "").split()).casefold()


CHANNEL_OVERRIDES_NORMALIZED = {
    normalize_channel_name(name): settings
    for name, settings in CHANNEL_OVERRIDES.items()
}


def parse_datetime(value):
    """Parsuje datę ISO 8601 z API i zwraca datetime ze strefą czasową."""
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

        # Jeśli API zwróci datę bez strefy, traktujemy ją jako UTC.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt

    except (ValueError, TypeError, AttributeError):
        return None


def xmltv_datetime(value):
    """Konwertuje datę do formatu XMLTV w czasie warszawskim."""
    dt = parse_datetime(value)

    if dt is None:
        return None

    dt = dt.astimezone(WARSAW_TZ)
    return dt.strftime("%Y%m%d%H%M%S %z")


def get_json(session, url, params):
    """Pobiera JSON z API z ponawianiem żądań."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()

        except (requests.RequestException, ValueError) as exc:
            logging.warning(
                "Błąd pobierania (%d/%d): %s",
                attempt,
                MAX_RETRIES,
                exc,
            )

            if attempt < MAX_RETRIES:
                time.sleep(attempt * 2)

    return None


def get_channels(session, start, end):
    """Pobiera wszystkie strony listy kanałów."""
    url = API_URL + "live_channels"

    params = PARAMS.copy()
    params.update({
        "epg_starts_at": start.strftime("%Y-%m-%dT%H:00:00.000Z"),
        "epg_ends_at": end.strftime("%Y-%m-%dT%H:00:00.000Z"),
        "per_page": str(PAGE_SIZE),
    })

    channels = []
    page = 1

    while True:
        params["page"] = str(page)
        result = get_json(session, url, params)

        if result is None:
            raise RuntimeError(
                "Nie udało się pobrać listy kanałów. "
                "Przerwano, aby nie zapisać niepełnego EPG."
            )

        data = result.get("data", [])
        channels.extend(data)

        pagination = result.get("meta", {}).get("pagination", {})
        current = pagination.get("page", page)
        total = pagination.get("total_pages", current)

        logging.info(
            "Pobrano stronę kanałów %s/%s",
            current,
            total,
        )

        if current >= total:
            break

        page += 1

    return channels


def has_polish_audio(channel):
    """Sprawdza, czy kanał oferuje polską ścieżkę audio."""
    languages = channel.get("labels", {}).get("languages", [])

    return any(
        isinstance(language, dict) and language.get("id") == "POL"
        for language in languages
    )


def add_text(parent, tag, text, lang=None):
    """Dodaje element tekstowy XML."""
    element = ET.SubElement(parent, tag)

    if lang:
        element.set(
            "{http://www.w3.org/XML/1998/namespace}lang",
            lang,
        )

    element.text = str(text or "")
    return element


def main():
    parser = argparse.ArgumentParser(
        description="Generator EPG XMLTV dla Rakuten TV Polska"
    )
    parser.add_argument(
        "-o", "--output",
        default=DEFAULT_OUTPUT,
        help="Plik wynikowy XMLTV (domyślnie rakuten.xml)",
    )
    parser.add_argument(
        "--past",
        type=float,
        default=5,
        help="Liczba godzin EPG wstecz (domyślnie 2)",
    )
    parser.add_argument(
        "--future",
        type=float,
        default=30,
        help="Liczba godzin EPG naprzód (domyślnie 12)",
    )
    parser.add_argument(
        "--minify",
        action="store_true",
        help="Zapisz XML bez wcięć",
    )
    args = parser.parse_args()

    if args.past < 0 or args.future <= 0:
        parser.error("--past musi być >= 0, a --future musi być > 0")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Zakres API wyznaczamy w UTC.
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=args.past)
    end = now + timedelta(hours=args.future)

    session = requests.Session()
    session.headers.update(HEADERS)

    logging.info("Pobieranie kanałów Rakuten TV Polska...")

    try:
        channels = get_channels(session, start, end)
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 1
    finally:
        session.close()

    # Ograniczamy wynik do kanałów z polską ścieżką audio.
    channels = [
        channel for channel in channels
        if has_polish_audio(channel)
    ]

    if not channels:
        logging.error(
            "API nie zwróciło kanałów z polską ścieżką audio. "
            "Nie zapisano pustego EPG."
        )
        return 1

    logging.info(
        "Kanały z polską ścieżką audio: %d",
        len(channels),
    )

    tv = ET.Element("tv", {
        "generator-info-name": "Rakuten TV PL EPG",
        "generator-info-url": BASE_URL,
    })

    programme_count = 0
    channel_ids = set()

    # Programy przechowujemy osobno, aby wszystkie kanały
    # znalazły się na początku pliku XMLTV.
    programmes_element = ET.Element("programmes")

    for channel in channels:
        cid = channel.get("id")
        name = channel.get("title") or cid

        if not cid:
            logging.warning("Pominięto kanał bez ID: %s", name)
            continue

        # Dopasowanie ręcznych ustawień po nazwie kanału.
        override = CHANNEL_OVERRIDES_NORMALIZED.get(
            normalize_channel_name(name),
            {},
        )

        # Można nadpisać ID XMLTV; bez ustawienia używana jest nazwa kanału.
        channel_id = str(override.get("id") or name)

        # Ochrona przed ewentualnymi duplikatami kanałów.
        if channel_id in channel_ids:
            logging.warning(
                "Pominięto kanał %r: ID XMLTV %r jest już używane.",
                name,
                channel_id,
            )
            continue

        channel_ids.add(channel_id)

        # Definicje kanałów dodajemy bezpośrednio do <tv>.
        ch_element = ET.SubElement(
            tv,
            "channel",
            {"id": channel_id},
        )

        # Nazwa wyświetlana pozostaje oryginalna; zmieniamy tylko ID, jeśli skonfigurowano.
        add_text(ch_element, "display-name", name, "pl")

        images = channel.get("images") or {}
        # Ręczne logo ma pierwszeństwo przed logo z API Rakuten.
        logo = override.get("logo") or images.get("artwork")

        if logo:
            ET.SubElement(ch_element, "icon", {"src": logo})

        if override:
            logging.info(
                "Zastosowano ustawienia ręczne dla kanału %r (ID XMLTV: %s)",
                name,
                channel_id,
            )

        programs = channel.get("live_programs") or []
        seen_programmes = set()

        for program in programs:
            start_raw = program.get("starts_at")
            end_raw = program.get("ends_at")

            start_xml = xmltv_datetime(start_raw)
            end_xml = xmltv_datetime(end_raw)

            if not start_xml or not end_xml:
                continue

            start_dt = parse_datetime(start_raw)
            end_dt = parse_datetime(end_raw)

            if not start_dt or not end_dt or end_dt <= start_dt:
                continue

            # Porównujemy momenty emisji w UTC.
            start_dt = start_dt.astimezone(timezone.utc)
            end_dt = end_dt.astimezone(timezone.utc)

            # Pomijamy programy poza żądanym zakresem.
            if end_dt <= start or start_dt >= end:
                continue

            title = (program.get("title") or "").strip()
            description = (program.get("description") or "").strip()

            if not title:
                continue

            key = (start_xml, end_xml, title)

            if key in seen_programmes:
                continue

            seen_programmes.add(key)

            # Pozycje programu gromadzimy w osobnym elemencie.
            p_element = ET.SubElement(
                programmes_element,
                "programme",
                {
                    "start": start_xml,
                    "stop": end_xml,
                    "channel": channel_id,
                },
            )

            add_text(p_element, "title", title, "pl")

            if description:
                add_text(p_element, "desc", description, "pl")

            programme_count += 1

    if not channel_ids:
        logging.error("Nie znaleziono poprawnych kanałów.")
        return 1

    # Dodajemy wszystkie programy za definicjami kanałów.
    tv.extend(list(programmes_element))

    # Czytelne wcięcia XML, jeśli nie wybrano --minify.
    if not args.minify:
        ET.indent(tv, space="  ")

    output = Path(args.output).expanduser()

    try:
        output.parent.mkdir(parents=True, exist_ok=True)

        # Zapis najpierw do pliku tymczasowego.
        temp_output = output.with_name(output.name + ".tmp")

        tree = ET.ElementTree(tv)
        tree.write(
            str(temp_output),
            encoding="utf-8",
            xml_declaration=True,
        )

        # Zastąpienie pliku dopiero po poprawnym wygenerowaniu.
        temp_output.replace(output)

    except OSError as exc:
        logging.error("Nie udało się zapisać EPG: %s", exc)
        return 1

    logging.info("Zapisano EPG: %s", output.resolve())
    logging.info("Kanały: %d", len(channel_ids))
    logging.info("Pozycje programu: %d", programme_count)

    return 0


if __name__ == "__main__":
    sys.exit(main())
