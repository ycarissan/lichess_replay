"""
Lichess Failed Puzzles Replay
==============================
Petit site Flask qui :
  1. authentifie l'utilisateur via OAuth2 + PKCE ("Log in with Lichess"),
  2. récupère son activité de puzzles (GET /api/puzzle/activity, scope puzzle:read),
  3. filtre les 10 derniers puzzles RATÉS (win == false),
  4. permet de les rejouer sur un échiquier interactif (chess.js + chessboard.js).

Doc officielle :
  - OAuth2 PKCE : https://lichess.org/api#section/Authentication
  - Puzzle activity : https://lichess.org/api#tag/Puzzles/operation/apiPuzzleActivity
"""

import base64
import hashlib
import os
import secrets
import urllib.parse

import requests
from flask import Flask, redirect, render_template, request, session, url_for

from supabase_client import get_supabase

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

# En production (derrière HTTPS chez Render/Railway), on sécurise le cookie.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") == "production"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# --- Configuration OAuth2 -----------------------------------------------
# client_id : chaîne arbitraire choisie par vous, doit rester constante.
# redirect_uri : doit être EXACTEMENT celle utilisée lors du login (localhost en dev).
LICHESS_CLIENT_ID = os.environ.get("LICHESS_CLIENT_ID", "mon-app-puzzle-replay")
REDIRECT_URI = os.environ.get("LICHESS_REDIRECT_URI", "http://localhost:5000/callback")

AUTHORIZE_URL = "https://lichess.org/oauth"
TOKEN_URL = "https://lichess.org/api/token"
API_BASE = "https://lichess.org/api"
SCOPE = "puzzle:read"


# --- Utilitaires PKCE ----------------------------------------------------
def generate_pkce_pair():
    """Génère (code_verifier, code_challenge) selon RFC 7636 (méthode S256)."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


# --- Routes ----------------------------------------------------------------
@app.route("/")
def index():
    if "access_token" in session:
        return redirect(url_for("puzzles"))
    return render_template("index.html")


@app.route("/login")
def login():
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(24)

    session["code_verifier"] = code_verifier
    session["oauth_state"] = state

    params = {
        "response_type": "code",
        "client_id": LICHESS_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
        "state": state,
    }
    return redirect(f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}")


@app.route("/callback")
def callback():
    error = request.args.get("error")
    if error:
        return render_template("index.html", error=f"Autorisation refusée : {error}")

    if request.args.get("state") != session.get("oauth_state"):
        return render_template("index.html", error="État OAuth invalide (state mismatch)."), 400

    code = request.args.get("code")
    if not code:
        return render_template("index.html", error="Code d'autorisation manquant."), 400

    # Échange du code contre un access token (pas de client_secret : flux PKCE public)
    token_resp = requests.post(
        TOKEN_URL,
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": LICHESS_CLIENT_ID,
            "code_verifier": session.get("code_verifier"),
        },
        timeout=15,
    )

    if token_resp.status_code != 200:
        return render_template(
            "index.html",
            error=f"Échec de l'échange du token ({token_resp.status_code}) : {token_resp.text}",
        ), 400

    token_data = token_resp.json()
    session["access_token"] = token_data["access_token"]
    session.pop("code_verifier", None)
    session.pop("oauth_state", None)

    return redirect(url_for("puzzles"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/puzzles")
def puzzles():
    access_token = session.get("access_token")
    if not access_token:
        return redirect(url_for("index"))

    headers = {"Authorization": f"Bearer {access_token}"}

    # On demande un peu de marge (max=200) car l'endpoint ne filtre pas
    # nativement sur "raté uniquement" : le filtrage se fait côté client.
    resp = requests.get(
        f"{API_BASE}/puzzle/activity",
        headers=headers,
        params={"max": 200},
        timeout=20,
        stream=True,
    )

    if resp.status_code == 401:
        session.clear()
        return render_template("index.html", error="Session expirée, merci de vous reconnecter."), 401

    if resp.status_code != 200:
        return render_template("puzzles.html", error=f"Erreur API Lichess ({resp.status_code})", failed=[])

    import json

    failed = []
    for line in resp.iter_lines():
        if not line:
            continue
        entry = json.loads(line)
        if entry.get("win") is False:
            failed.append(entry)
        if len(failed) >= 10:
            break  # déjà triés du plus récent au plus ancien par l'API

    return render_template("puzzles.html", failed=failed, error=None)


def _find_puzzle_entry(puzzle_id, access_token):
    """Cherche un puzzle par id dans les 200 dernières activités de puzzle
    de l'utilisateur. Retourne l'entrée complète (dict) ou None."""
    import json

    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(
        f"{API_BASE}/puzzle/activity",
        headers=headers,
        params={"max": 200},
        timeout=20,
        stream=True,
    )
    if resp.status_code != 200:
        return None
    for line in resp.iter_lines():
        if not line:
            continue
        entry = json.loads(line)
        if entry.get("puzzle", {}).get("id") == puzzle_id:
            return entry
    return None


@app.route("/api/puzzle-info/<puzzle_id>")
def api_puzzle_info(puzzle_id):
    """Endpoint JSON léger : renvoie fen/rating/themes d'un puzzle précis.
    Utilisé côté client pour compléter les puzzles suivis en localStorage
    avant l'ajout de l'aperçu de position (qui n'avaient donc pas de FEN),
    ou tout puzzle sorti de la fenêtre des 200 dernières activités."""
    access_token = session.get("access_token")
    if not access_token:
        return {"error": "not_authenticated"}, 401

    entry = _find_puzzle_entry(puzzle_id, access_token)
    if entry is None:
        return {"error": "not_found"}, 404

    puzzle = entry["puzzle"]
    return {
        "id": puzzle_id,
        "fen": puzzle.get("fen"),
        "rating": puzzle.get("rating"),
        "themes": puzzle.get("themes", []),
    }


@app.route("/replay/<puzzle_id>")
def replay(puzzle_id):
    access_token = session.get("access_token")
    if not access_token:
        return redirect(url_for("index"))

    target = _find_puzzle_entry(puzzle_id, access_token)

    if target is None:
        return render_template("replay.html", error="Puzzle introuvable.", puzzle=None)

    puzzle = target["puzzle"]
    fen = puzzle.get("fen")
    solution = puzzle.get("solution", [])  # liste de coups UCI

    # Journalisation optionnelle dans Supabase (no-op si SUPABASE_URL/KEY absents)
    sb = get_supabase()
    if sb:
        try:
            sb.table("replayed_puzzles").insert(
                {"puzzle_id": puzzle_id, "rating": puzzle.get("rating")}
            ).execute()
        except Exception:
            pass  # on ne bloque jamais le replay si Supabase est indisponible

    return render_template(
        "replay.html",
        error=None,
        puzzle_id=puzzle_id,
        fen=fen,
        solution=solution,
        rating=puzzle.get("rating"),
        themes=puzzle.get("themes", []),
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
