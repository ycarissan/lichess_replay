"""
Connexion optionnelle à Supabase.

L'app fonctionne sans Supabase : ce module n'est utilisé que si les
variables d'environnement SUPABASE_URL et SUPABASE_KEY sont définies.
Cas d'usage typiques :
  - garder un historique des puzzles déjà rejoués (éviter les doublons),
  - stocker des statistiques par utilisateur (nombre de puzzles rejoués,
    progression, etc.).

Utilisation dans app.py :

    from supabase_client import get_supabase

    sb = get_supabase()
    if sb:
        sb.table("replayed_puzzles").insert({
            "puzzle_id": puzzle_id,
            "lichess_username": username,
        }).execute()
"""

import os

_client = None


def get_supabase():
    """Retourne un client Supabase initialisé, ou None si non configuré."""
    global _client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        return None

    if _client is None:
        from supabase import create_client
        _client = create_client(url, key)

    return _client
