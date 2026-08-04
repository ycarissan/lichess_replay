"""
Import de la liste des joueurs FIDE dans Supabase (table fide_players).
=========================================================================

FIDE ne propose pas d'API de recherche : seule une liste complète est
publiée (mensuellement) au format XML/TXT sur ratings.fide.com.
Voir : https://ratings.fide.com/download_lists.phtml

Ce script :
  1. télécharge le fichier XML complet (~45 Mo, tous titres/fédérations),
  2. le parse,
  3. upsert les joueurs dans la table Supabase `fide_players`
     (créée par scripts/create_coach_tables.sql).

L'autocomplétion de l'application interroge ensuite CETTE table locale
(recherche par préfixe), sans jamais appeler ratings.fide.com en direct :
plus rapide, pas de dépendance à la disponibilité du site FIDE au moment
où un entraîneur tape un nom.

Usage :
    python scripts/import_fide_players.py

Variables d'environnement requises : SUPABASE_URL, SUPABASE_KEY
(la clé doit avoir le droit d'écrire dans fide_players — service_role).

À planifier périodiquement (FIDE republie la liste chaque mois) : cron
externe, GitHub Action, ou tâche planifiée Render.
"""

import io
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

import requests

FIDE_XML_URL = "https://ratings.fide.com/download/players_list_xml.zip"
BATCH_SIZE = 1000


def download_and_extract_xml():
    print(f"Téléchargement de {FIDE_XML_URL} ...")
    resp = requests.get(FIDE_XML_URL, timeout=120)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        # Le zip FIDE contient un unique fichier .xml (nommage variable
        # selon les mois, ex. players_list_xml_foa.xml).
        xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not xml_names:
            raise RuntimeError("Aucun fichier .xml trouvé dans l'archive FIDE.")
        print(f"Extraction de {xml_names[0]} ...")
        return zf.read(xml_names[0])


def _int_or_none(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def parse_players(xml_bytes):
    """Parse le XML FIDE et yield un dict par joueur, prêt pour upsert."""
    context = ET.iterparse(io.BytesIO(xml_bytes), events=("end",))
    for _, elem in context:
        if elem.tag != "player":
            continue

        def field(tag):
            child = elem.find(tag)
            return child.text.strip() if child is not None and child.text else None

        fide_id = _int_or_none(field("fideid"))
        name = field("name")
        if fide_id is None or not name:
            elem.clear()
            continue

        yield {
            "fide_id": fide_id,
            "name": name,
            "federation": field("country"),
            "sex": field("sex"),
            "title": field("title"),
            "standard_rating": _int_or_none(field("rating")),
            "rapid_rating": _int_or_none(field("rapid_rating")),
            "blitz_rating": _int_or_none(field("blitz_rating")),
            "birth_year": _int_or_none(field("birthday")),
        }
        elem.clear()


def main():
    from supabase_client import get_supabase

    sb = get_supabase()
    if not sb:
        print("Supabase non configuré (SUPABASE_URL / SUPABASE_KEY manquants).", file=sys.stderr)
        sys.exit(1)

    xml_bytes = download_and_extract_xml()

    batch = []
    total = 0
    for player in parse_players(xml_bytes):
        batch.append(player)
        if len(batch) >= BATCH_SIZE:
            sb.table("fide_players").upsert(batch, on_conflict="fide_id").execute()
            total += len(batch)
            print(f"{total} joueurs importés...", end="\r")
            batch = []

    if batch:
        sb.table("fide_players").upsert(batch, on_conflict="fide_id").execute()
        total += len(batch)

    print(f"\nImport terminé : {total} joueurs dans fide_players.")


if __name__ == "__main__":
    main()
