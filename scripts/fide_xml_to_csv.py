"""
Convertit la liste FIDE (XML) en CSV, pour ouverture rapide dans
LibreOffice Calc (le filtre XML générique de Calc est très lent sur les
~500 000 lignes du fichier FIDE ; le CSV se charge quasi instantanément).

Usage :
    python scripts/fide_xml_to_csv.py players_list_xml_foa.xml joueurs_fide.csv

Le fichier XML source s'obtient en téléchargeant et dézippant :
    https://ratings.fide.com/download/players_list_xml.zip
"""

import csv
import sys
import xml.etree.ElementTree as ET

FIELDS = [
    "fide_id", "name", "federation", "sex", "title",
    "standard_rating", "rapid_rating", "blitz_rating", "birth_year",
]


def parse_players(xml_path):
    """Parse en streaming (iterparse) : ne charge jamais tout le fichier
    en mémoire d'un coup, contrairement à ET.parse()."""
    for _, elem in ET.iterparse(xml_path, events=("end",)):
        if elem.tag != "player":
            continue

        def field(tag):
            child = elem.find(tag)
            return child.text.strip() if child is not None and child.text else ""

        yield {
            "fide_id": field("fideid"),
            "name": field("name"),
            "federation": field("country"),
            "sex": field("sex"),
            "title": field("title"),
            "standard_rating": field("rating"),
            "rapid_rating": field("rapid_rating"),
            "blitz_rating": field("blitz_rating"),
            "birth_year": field("birthday"),
        }
        elem.clear()


def main():
    if len(sys.argv) != 3:
        print("Usage : python scripts/fide_xml_to_csv.py <fichier.xml> <sortie.csv>")
        sys.exit(1)

    xml_path, csv_path = sys.argv[1], sys.argv[2]

    # encoding="utf-8-sig" : ajoute un BOM, pour que LibreOffice Calc
    # détecte automatiquement l'UTF-8 à l'ouverture sans dialogue manuel.
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        count = 0
        for player in parse_players(xml_path):
            writer.writerow(player)
            count += 1
            if count % 20000 == 0:
                print(f"{count} joueurs écrits...", end="\r")

    print(f"\nTerminé : {count} joueurs écrits dans {csv_path}")


if __name__ == "__main__":
    main()
