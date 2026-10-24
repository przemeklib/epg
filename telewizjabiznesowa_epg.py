#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telewizja Biznesowa (tbpl) -> XMLTV EPG

Pobiera harmonogram z API MediaTool i zapisuje program w formacie XMLTV.
Domyślnie zapisuje dzisiejszy dzień oraz dwa kolejne dni.

Wymagania:
    python3 -m pip install requests

Uruchomienie:
    python3 telewizjabiznesowa_epg.py

Opcje:
    python3 telewizjabiznesowa_epg.py --days 2
    python3 telewizjabiznesowa_epg.py -o /ścieżka/telewizjabiznesowa.xml
    python3 telewizjabiznesowa_epg.py --channel-id telewizjabiznesowa.pl

Uwaga:
- Parametr --days oznacza liczbę dni naprzód oprócz dzisiejszego dnia.
  --days 2 obejmuje dziś, jutro i pojutrze.
- Ustaw CHANNEL_TOKEN 
"""

import argparse
import html
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, time as dt_time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE_DIR = Path(__file__).resolve().parent
API_URL = "https://app.mediatool.tv/api/epg-api/information/channel/tbpl/weeks/1"
TIMEZONE =  ZoneInfo("Europe/Warsaw") #timezone.utc
DEFAULT_OUTPUT = BASE_DIR / "telewizjabiznesowa.xml"
#USER_AGENT = "Mozilla/5.0 (compatible; XMLTV-EPG/1.0)"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
CHANNEL_TOKEN='86e89a49-9e7c-48da-8c29-7db6807e8f8b'
LOGO = "https://epg.ovh/logo/TV+Biznesowa.png"

def parse_datetime(value):
    """Zachowuje godzinę z API i interpretuje ją jako czas polski."""
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

        # Usuwamy źródłową strefę bez przeliczania godziny.
        # Następnie przypisujemy strefę docelową.
        parsed = parsed.replace(tzinfo=None)
        return parsed.replace(tzinfo=TIMEZONE)

    except (ValueError, TypeError):
        logging.warning("Nie można odczytać daty: %r", value)
        return None

def localized_text(value, language="AB"):
    """Wydobywa tekst z pola, które może być zwykłym stringiem lub mapą języków."""
    if isinstance(value, dict):
        text = value.get(language)
        if text is None:
            # Awaryjnie wybierz pierwszą niepustą wartość tekstową.
            text = next((v for v in value.values() if isinstance(v, str) and v.strip()), "")
        return str(text).strip() if text is not None else ""
    if isinstance(value, str):
        return value.strip()
    return ""


def add_text(parent, tag, value, **attrs):
    node = ET.SubElement(parent, tag, attrs)
    node.text = value
    return node


def xmltv_timestamp(value):
    """XMLTV zapisuje czas lokalny wraz z przesunięciem względem UTC."""
#    value = value.astimezone(timezone.utc)
    return value.strftime("%Y%m%d%H%M%S %z")

#def xmltv_timestamp(value):
#    """Zapisuje czas w UTC w formacie XMLTV."""
#    value = value.astimezone(timezone.utc)
#    return value.strftime("%Y%m%d%H%M%S +0000")


def fetch_schedule(token, timeout):
    url = API_URL
    started = time.monotonic()
    try:
        response = requests.get(
            url,
            params={"token": token},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=(15, timeout),
        )
        elapsed = time.monotonic() - started
        response.raise_for_status()
        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise RuntimeError("API nie zwróciło poprawnego JSON-a.") from exc
        logging.info(
            "Pobrano odpowiedź HTTP %s w %.2f s (%s bajtów).",
            response.status_code, elapsed, len(response.content)
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Błąd pobierania danych z API: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("Nieoczekiwany format odpowiedzi API: oczekiwano obiektu JSON.")
    schedule = data.get("schedule")
    if not isinstance(schedule, list):
        keys = ", ".join(data.keys())
        raise RuntimeError(f"Brak listy 'schedule' w odpowiedzi API. Dostępne pola: {keys}")
    return schedule


def programme_bounds(now, days_ahead):
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Koniec jest wyłączny: przy --days 2 obejmujemy dziś, jutro i pojutrze.
    end_date = start.date() + timedelta(days=days_ahead + 1)
    end = datetime.combine(end_date, dt_time.min, tzinfo=TIMEZONE)
    return start, end


def build_xml(schedule, output, days_ahead, channel_id, channel_name):
    now = datetime.now(TIMEZONE)
    start_bound, end_bound = programme_bounds(now, days_ahead)

    root = ET.Element("tv", {"source-info-name": "MediaTool", "generator-info-name": "telewizjabiznesowa_epg.py"})
    channel = ET.SubElement(root, "channel", {"id": channel_id})
    add_text(channel, "display-name", channel_name, lang="pl")
    ET.SubElement(channel,"icon", {"src": LOGO})

    programmes = []
    skipped = 0
    for item in schedule:
        if not isinstance(item, dict):
            skipped += 1
            continue

        start = parse_datetime(item.get("startTime"))
        end = parse_datetime(item.get("endTime"))
        if not start or not end or end <= start:
            skipped += 1
            continue

        # Zachowujemy audycje przecinające wybrany zakres.
        if end <= start_bound or start >= end_bound:
            continue

        title = localized_text(item.get("title"))
        episode_title = localized_text(item.get("episodeTitle"))
        if not title:
            title = episode_title or "Program"

        programme = ET.Element(
            "programme",
            {
                "start": xmltv_timestamp(start),
                "stop": xmltv_timestamp(end),
                "channel": channel_id,
            },
        )
        add_text(programme, "title", title, lang="pl")
        if episode_title and episode_title.casefold() != title.casefold():
            add_text(programme, "sub-title", episode_title, lang="pl")

        # Dodatkowe pola dodajemy tylko wtedy, gdy faktycznie są obecne w JSON-ie.
   # Pełny opis audycji: synopsis.PL.longSynopsis
        synopsis = item.get("synopsis")
        description = ""

        if isinstance(synopsis, dict):
            synopsis_pl = synopsis.get("PL")
            if isinstance(synopsis_pl, dict):
                long_synopsis = synopsis_pl.get("longSynopsis")
                if isinstance(long_synopsis, str):
                    description = long_synopsis.strip()

        # Awaryjnie wykorzystaj dotychczasowe pole description.
        if not description:
            description = localized_text(item.get("description"))

        if description:
            add_text(programme, "desc", description, lang="pl")

        # Obraz audycji: images.stillScene
        images = item.get("images")
        if isinstance(images, dict):
            image_url = images.get("stillScene")
            if isinstance(image_url, str) and image_url.strip():
                ET.SubElement(
                    programme,
                    "icon",
                    {"src": image_url.strip()}
                )

        # Data produkcji: productionDate, np. 2024-12-05.
        production_date = item.get("productionDate")
        if isinstance(production_date, str) and production_date.strip():
            try:
                date_value = datetime.strptime(
                    production_date.strip()[:10], "%Y-%m-%d"
                ).strftime("%Y%m%d")
                add_text(programme, "date", date_value)
            except ValueError:
                logging.warning(
                    "Nieprawidłowa data produkcji: %r", production_date
                )

        # Kategoria, jeśli występuje w odpowiedzi API.
        category = localized_text(item.get("category"))
        if category:
            add_text(programme, "category", category, lang="pl")

        programmes.append((start, programme))

    programmes.sort(key=lambda pair: pair[0])
    for _, programme in programmes:
        root.append(programme)

    tree = ET.ElementTree(root)
    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass

    output_path = Path(output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

    return output_path, len(programmes), skipped, start_bound, end_bound


def main():
    parser = argparse.ArgumentParser(description="Pobiera EPG Telewizji Biznesowej z MediaTool i zapisuje XMLTV.")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help=f"Plik wyjściowy (domyślnie: {DEFAULT_OUTPUT})")
    parser.add_argument("--days", type=int, default=1, help="Ile dni naprzód poza dzisiejszym dniem; domyślnie 2")
    parser.add_argument("--channel-id", default="Telewizja Biznesowa", help="Identyfikator kanału XMLTV")
    parser.add_argument("--channel-name", default="Telewizja Biznesowa", help="Nazwa kanału XMLTV")
    parser.add_argument("--timeout", type=int, default=120, help="Limit czasu odpowiedzi API w sekundach")
    parser.add_argument("-v", "--verbose", action="store_true", help="Więcej informacji diagnostycznych")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    if args.days < 0 or args.days > 6:
        parser.error("--days musi być w zakresie 0–6.")

    token = CHANNEL_TOKEN
    if not token:
        logging.error("Brak tokenu. Ustaw zmienną środowiskową CHANNEL_TOKEN.")
        logging.error("Przykład: export CHANNEL_TOKEN='TWÓJ_TOKEN'")
        return 2

    try:
        schedule = fetch_schedule(token, args.timeout)
        output, count, skipped, start, end = build_xml(
            schedule, args.output, args.days, args.channel_id, args.channel_name
        )
    except (RuntimeError, OSError) as exc:
        logging.error("%s", exc)
        return 1

    logging.info("Zakres EPG: %s – %s (koniec wyłączny).", start.isoformat(), end.isoformat())
    logging.info("Zapisano %d audycji do: %s", count, output.resolve())
    if skipped:
        logging.warning("Pominięto %d nieprawidłowych rekordów.", skipped)
    if count == 0:
        logging.warning("Nie znaleziono audycji w wybranym zakresie. Sprawdź zakres API i format dat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
