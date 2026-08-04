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

"""
Import / statistiques de la liste des joueurs FIDE.
=========================================================================

FIDE ne propose pas d'API de recherche : seule une liste complète est
publiée (mensuellement) au format XML/TXT sur ratings.fide.com.
Voir : https://ratings.fide.com/download_lists.phtml

Ce script télécharge et parse toujours le fichier XML complet (~45 Mo).
Deux modes :

  - Par défaut (sans argument) : AUCUNE écriture dans Supabase. Le script
    se contente d'afficher des statistiques (nombre de joueurs par
    fédération, statistiques Elo). Pratique pour un contrôle rapide sans
    toucher à la base en ligne.

  - Avec --update-supabase : en plus des statistiques, upsert les joueurs
    dans la table Supabase `fide_players` (créée par
    scripts/create_coach_tables.sql). C'est ce mode qu'utilise
    l'autocomplétion de l'application (recherche par préfixe sur cette
    table locale, sans jamais appeler ratings.fide.com en direct).

Usage :
    python scripts/import_fide_players.py                  # stats seulement
    python scripts/import_fide_players.py --update-supabase # stats + import

Variables d'environnement requises SEULEMENT avec --update-supabase :
SUPABASE_URL, SUPABASE_KEY (clé avec droit d'écriture sur fide_players —
service_role).

À planifier périodiquement (FIDE republie la liste chaque mois) : cron
externe, GitHub Action, ou tâche planifiée Render.
"""

import argparse
import io
import os
import statistics
import sys
from collections import Counter

# Permet d'exécuter ce script depuis n'importe où (ex. `python
# scripts/import_fide_players.py` depuis la racine) en ajoutant la racine
# du projet à sys.path, pour trouver supabase_client.py qui s'y trouve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import zipfile
import xml.etree.ElementTree as ET

import requests

FIDE_XML_URL = "https://ratings.fide.com/download/players_list_xml.zip"
BATCH_SIZE = 1000
TOP_N_FEDERATIONS = 20
LOCAL_XML_CACHE = "fide_players_list.xml"


def _format_progress(downloaded, total):
    mo_done = downloaded / 1_000_000
    if total:
        pct = 100 * downloaded / total
        mo_total = total / 1_000_000
        bar_len = 30
        filled = int(bar_len * downloaded / total)
        bar = "█" * filled + "-" * (bar_len - filled)
        return f"\r  [{bar}] {pct:5.1f}%  {mo_done:6.1f} / {mo_total:.1f} Mo"
    return f"\r  {mo_done:6.1f} Mo téléchargés..."


def download_and_extract_xml():
    print(f"Téléchargement de {FIDE_XML_URL} ...", file=sys.stderr)
    resp = requests.get(FIDE_XML_URL, stream=True, timeout=120)
    resp.raise_for_status()

    total_size = int(resp.headers.get("content-length", 0))
    chunks = []
    downloaded = 0
    for chunk in resp.iter_content(chunk_size=1 << 16):  # 64 Ko par lot
        if not chunk:
            continue
        chunks.append(chunk)
        downloaded += len(chunk)
        print(_format_progress(downloaded, total_size), end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)  # saut de ligne après la barre de progression

    content = b"".join(chunks)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        # Le zip FIDE contient un unique fichier .xml (nommage variable
        # selon les mois, ex. players_list_xml_foa.xml).
        xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not xml_names:
            raise RuntimeError("Aucun fichier .xml trouvé dans l'archive FIDE.")
        print(f"Extraction de {xml_names[0]} ...", file=sys.stderr)
        return zf.read(xml_names[0])


def get_xml_bytes(force_download=False, cache_path=LOCAL_XML_CACHE):
    """Renvoie le contenu XML FIDE, en réutilisant le cache local
    (cache_path, dans le répertoire courant) s'il existe déjà et que
    force_download n'est pas demandé. Sinon télécharge depuis FIDE et
    écrit/écrase le cache pour les prochains lancements.

    ATTENTION : FIDE republie sa liste chaque mois, donc un cache ancien
    peut devenir périmé — utilisez --force-download pour le rafraîchir."""
    if not force_download and os.path.exists(cache_path):
        print(f"Fichier local '{cache_path}' trouvé : pas de nouveau téléchargement "
              f"(utilisez --force-download pour le rafraîchir).", file=sys.stderr)
        with open(cache_path, "rb") as f:
            return f.read()

    xml_bytes = download_and_extract_xml()
    with open(cache_path, "wb") as f:
        f.write(xml_bytes)
    print(f"Fichier sauvegardé localement : '{cache_path}' "
          f"({len(xml_bytes) / 1_000_000:.1f} Mo).", file=sys.stderr)
    return xml_bytes


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


def _print_elo_stats(label, ratings, total_players):
    if not ratings:
        print(f"\n{label} : aucun joueur avec cette donnée renseignée.")
        return
    print(f"\n{label} ({len(ratings)} joueurs sur {total_players}, "
          f"{100 * len(ratings) / total_players:.1f}%) :")
    print(f"  min       : {min(ratings)}")
    print(f"  max       : {max(ratings)}")
    print(f"  moyenne   : {statistics.mean(ratings):.1f}")
    print(f"  médiane   : {statistics.median(ratings):.1f}")
    if len(ratings) > 1:
        print(f"  écart-type: {statistics.stdev(ratings):.1f}")


def print_statistics(total, country_counts, standard_ratings, rapid_ratings, blitz_ratings):
    if total == 0:
        print("\n=== Statistiques FIDE : aucun joueur à analyser ===")
        return

    print(f"\n=== Statistiques FIDE ({total} joueurs au total, "
          f"{len(country_counts)} fédérations) ===")

    print(f"\nTop {TOP_N_FEDERATIONS} fédérations par nombre de joueurs :")
    for fed, count in country_counts.most_common(TOP_N_FEDERATIONS):
        pct = 100 * count / total
        print(f"  {fed or '??':5s} {count:7d} ({pct:5.1f}%)")

    _print_elo_stats("Elo standard", standard_ratings, total)
    _print_elo_stats("Elo rapide", rapid_ratings, total)
    _print_elo_stats("Elo blitz", blitz_ratings, total)


def main():
    parser = argparse.ArgumentParser(
        description="Télécharge la liste FIDE, affiche des statistiques, "
                     "et met à jour Supabase si --update-supabase est passé."
    )
    parser.add_argument(
        "--update-supabase",
        action="store_true",
        help="Met aussi à jour la table fide_players dans Supabase. "
             "Sans cette option, le script affiche uniquement des statistiques "
             "et n'écrit rien en ligne.",
    )
    parser.add_argument(
        "--federation",
        metavar="CODE",
        help="Ne traite (statistiques ET import) que les joueurs de cette "
             "fédération, code FIDE à 3 lettres (ex. FRA, GER, USA). "
             "Le fichier XML complet est toujours téléchargé (FIDE ne "
             "permet pas de filtrer côté serveur) ; seul le traitement "
             "local est restreint. Sans cette option, tous les pays sont traités.",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help=f"Force le re-téléchargement depuis FIDE même si le cache local "
             f"('{LOCAL_XML_CACHE}', dans le répertoire courant) existe déjà. "
             f"Sans cette option, le fichier local est réutilisé s'il est présent "
             f"(FIDE republie sa liste chaque mois : pensez à forcer périodiquement).",
    )
    args = parser.parse_args()
    federation_filter = args.federation.strip().upper() if args.federation else None

    sb = None
    if args.update_supabase:
        from supabase_client import get_supabase

        sb = get_supabase()
        if not sb:
            print("Supabase non configuré (SUPABASE_URL / SUPABASE_KEY manquants).", file=sys.stderr)
            sys.exit(1)

    xml_bytes = get_xml_bytes(force_download=args.force_download)

    if federation_filter:
        print(f"Filtre actif : fédération = {federation_filter}", file=sys.stderr)

    country_counts = Counter()
    standard_ratings = []
    rapid_ratings = []
    blitz_ratings = []
    total = 0
    total_seen = 0

    batch = []
    imported = 0

    for player in parse_players(xml_bytes):
        total_seen += 1
        if federation_filter and (player["federation"] or "").upper() != federation_filter:
            continue

        total += 1
        country_counts[player["federation"]] += 1
        if player["standard_rating"] is not None:
            standard_ratings.append(player["standard_rating"])
        if player["rapid_rating"] is not None:
            rapid_ratings.append(player["rapid_rating"])
        if player["blitz_rating"] is not None:
            blitz_ratings.append(player["blitz_rating"])

        if args.update_supabase:
            batch.append(player)
            if len(batch) >= BATCH_SIZE:
                sb.table("fide_players").upsert(batch, on_conflict="fide_id").execute()
                imported += len(batch)
                print(f"{imported} joueurs importés...", end="\r", file=sys.stderr)
                batch = []

    if federation_filter and total == 0:
        print(f"\nAucun joueur trouvé pour la fédération '{federation_filter}' "
              f"(sur {total_seen} joueurs lus au total) — vérifiez le code FIDE "
              f"(3 lettres, ex. FRA, GER, USA).", file=sys.stderr)

    if args.update_supabase:
        if batch:
            sb.table("fide_players").upsert(batch, on_conflict="fide_id").execute()
            imported += len(batch)
        scope = f"fédération {federation_filter}" if federation_filter else "toutes fédérations"
        print(f"\nImport terminé ({scope}) : {imported} joueurs écrits dans fide_players (Supabase).", file=sys.stderr)
    else:
        print("\nMode statistiques uniquement : aucune écriture dans Supabase "
              "(relancez avec --update-supabase pour mettre à jour la base).", file=sys.stderr)

    if federation_filter:
        print(f"(filtre fédération = {federation_filter} ; "
              f"{total} joueurs retenus sur {total_seen} lus dans le fichier FIDE complet)",
              file=sys.stderr)

    print_statistics(total, country_counts, standard_ratings, rapid_ratings, blitz_ratings)


if __name__ == "__main__":
    main()
