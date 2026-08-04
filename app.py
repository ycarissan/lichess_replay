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
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

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
MAX_LINKED_ACCOUNTS = 4  # total, compte principal inclus (fonctionnalité premium)

# Mêmes intervalles que static/leitner.js (système de Leitner, 5 boîtes).
LEITNER_INTERVALS_DAYS = {1: 1, 2: 3, 3: 7, 4: 16, 5: 35}
LEITNER_MAX_BOX = 5


def _leitner_next_review(box):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(days=LEITNER_INTERVALS_DAYS[box])).isoformat()


def is_premium_user(username):
    """Vérifie le statut premium dans Supabase (table premium_users).
    Renvoie False si Supabase n'est pas configuré, si l'utilisateur n'est
    pas identifié, ou en cas d'erreur (fail-safe : pas premium par défaut)."""
    if not username:
        return False
    sb = get_supabase()
    if not sb:
        return False
    try:
        resp = (
            sb.table("premium_users")
            .select("is_premium")
            .eq("lichess_username", username)
            .limit(1)
            .execute()
        )
        return bool(resp.data and resp.data[0].get("is_premium"))
    except Exception as exc:
        app.logger.error("Échec lecture premium_users pour %s : %s", username, exc)
        return False


def get_linked_accounts(primary_username):
    """Renvoie la liste des comptes Lichess liés au compte premium
    [{"username": ..., "access_token": ...}, ...], hors compte principal.
    Liste vide si non premium, Supabase indisponible, ou erreur."""
    sb = get_supabase()
    if not sb or not primary_username:
        return []
    try:
        resp = (
            sb.table("linked_lichess_accounts")
            .select("linked_username, access_token")
            .eq("premium_username", primary_username)
            .execute()
        )
        return [
            {"username": row["linked_username"], "access_token": row["access_token"]}
            for row in (resp.data or [])
        ]
    except Exception:
        return []


def get_all_accounts_for_session():
    """Renvoie la liste de TOUS les comptes utilisables pour cette session
    (compte principal + comptes liés si premium), sous la forme
    [{"username": ..., "access_token": ...}, ...]. Le compte principal est
    toujours en première position."""
    accounts = [{
        "username": session.get("lichess_username"),
        "access_token": session.get("access_token"),
    }]
    primary = session.get("lichess_username")
    if is_premium_user(primary):
        accounts.extend(get_linked_accounts(primary))
    return accounts


# --- Mode entraîneur -------------------------------------------------------
# Aucun rôle à cocher à l'inscription : quiconque visite /coach devient
# entraîneur automatiquement (une ligne `coaches` est créée au premier accès).
# Le lien Lichess d'un élève est OPTIONNEL (décision produit) : un élève peut
# n'être qu'un nom + éventuellement une fiche FIDE, sans compte Lichess propre.

def get_or_create_coach(username):
    """Renvoie l'id de la ligne `coaches` pour ce pseudo Lichess, en la
    créant si besoin. Renvoie None si Supabase n'est pas configuré."""
    sb = get_supabase()
    if not sb or not username:
        return None
    try:
        resp = (
            sb.table("coaches")
            .select("id")
            .eq("lichess_username", username)
            .limit(1)
            .execute()
        )
        if resp.data:
            return resp.data[0]["id"]
        created = sb.table("coaches").insert({
            "lichess_username": username,
            "display_name": username,
        }).execute()
        return created.data[0]["id"] if created.data else None
    except Exception as exc:
        app.logger.error("Échec get_or_create_coach pour %s : %s", username, exc)
        return None


def _next_class_name(coach_id, sb):
    """Propose le prochain nom de classe disponible : 'Classe 1', 'Classe 2', ...
    (le nom reste modifiable ensuite par l'entraîneur)."""
    resp = sb.table("classes").select("name").eq("coach_id", coach_id).execute()
    existing = {row["name"] for row in (resp.data or [])}
    n = 1
    while f"Classe {n}" in existing:
        n += 1
    return f"Classe {n}"


def search_students_autocomplete(coach_id, query, limit=8):
    """Autocomplétion de recherche d'élève : cherche d'abord parmi les
    élèves déjà créés par CET entraîneur (évite les doublons), puis dans le
    cache local `fide_players` (import périodique, voir
    scripts/import_fide_players.py — pas d'appel direct à ratings.fide.com).
    Renvoie une liste de dicts avec un champ 'source' ('existing' | 'fide')."""
    sb = get_supabase()
    if not sb or not query or len(query.strip()) < 2:
        return []
    q = query.strip()
    q_lower = q.lower()

    results = []
    try:
        own = (
            sb.table("students")
            .select("id, display_name, fide_id, fide_federation, fide_title, lichess_username")
            .eq("coach_id", coach_id)
            .like("display_name_lower", f"{q_lower}%")
            .limit(limit)
            .execute()
        )
        for row in own.data or []:
            results.append({
                "source": "existing",
                "student_id": row["id"],
                "name": row["display_name"],
                "federation": row.get("fide_federation"),
                "title": row.get("fide_title"),
                "fide_id": row.get("fide_id"),
                "lichess_username": row.get("lichess_username"),
            })
    except Exception as exc:
        app.logger.error("Échec recherche students pour coach %s : %s", coach_id, exc)

    remaining = limit - len(results)
    if remaining > 0:
        try:
            fide = (
                sb.table("fide_players")
                .select("fide_id, name, federation, title")
                .like("name_lower", f"{q_lower}%")
                .limit(remaining)
                .execute()
            )
            for row in fide.data or []:
                results.append({
                    "source": "fide",
                    "student_id": None,
                    "name": row["name"],
                    "federation": row.get("federation"),
                    "title": row.get("title"),
                    "fide_id": row.get("fide_id"),
                    "lichess_username": None,
                })
        except Exception as exc:
            app.logger.error("Échec recherche fide_players pour %r : %s", q, exc)

    return results


# --- Utilitaires PKCE ----------------------------------------------------
def generate_pkce_pair():
    """Génère (code_verifier, code_challenge) selon RFC 7636 (méthode S256)."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


# --- Routes ----------------------------------------------------------------
@app.route("/.well-known/assetlinks.json")
def assetlinks():
    """Fichier de vérification Digital Asset Links, requis pour qu'une TWA
    (Trusted Web Activity) Android affiche le site sans barre d'adresse.

    Le champ sha256_cert_fingerprints doit être rempli avec l'empreinte de
    la clé de signature de l'app Android, générée par Bubblewrap
    (`bubblewrap build`, fichier android.keystore) — PAS disponible avant
    d'avoir généré l'app Android. Configurez-le via la variable
    d'environnement ANDROID_APP_SHA256_FINGERPRINT sur Render.
    Format attendu : paires d'octets en majuscules séparées par ':'
    (ex. "14:6D:E9:83:C5:73:...").
    """
    fingerprint = os.environ.get("ANDROID_APP_SHA256_FINGERPRINT")
    package_name = os.environ.get("ANDROID_APP_PACKAGE_NAME", "com.example.puzzlereplay.twa")

    if not fingerprint:
        # Pas encore configuré : renvoie un tableau vide (aucune app liée)
        # plutôt qu'une erreur, pour ne jamais casser le site principal.
        return jsonify([])

    return jsonify([{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {
            "namespace": "android_app",
            "package_name": package_name,
            "sha256_cert_fingerprints": [fingerprint],
        },
    }])


@app.route("/")
def index():
    if "access_token" in session:
        return redirect(url_for("puzzles"))
    return render_template("index.html")


@app.route("/login")
def login():
    return _start_oauth(linking=False)


@app.route("/link-account")
def link_account():
    """Démarre une nouvelle authentification OAuth pour LIER un compte
    Lichess supplémentaire au compte premium actuellement connecté, au
    lieu de remplacer la session en cours."""
    if "access_token" not in session:
        return redirect(url_for("index"))
    if not is_premium_user(session.get("lichess_username")):
        return redirect(url_for("puzzles"))

    primary = session.get("lichess_username")
    total = 1 + len(get_linked_accounts(primary))
    if total >= MAX_LINKED_ACCOUNTS:
        return redirect(url_for("puzzles", link_error="max_reached"))

    session["primary_username"] = primary
    return _start_oauth(linking=True)


def _start_oauth(linking):
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(24)

    session["code_verifier"] = code_verifier
    session["oauth_state"] = state
    session["linking_mode"] = linking

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
    new_access_token = token_data["access_token"]
    linking_mode = session.pop("linking_mode", False)
    session.pop("code_verifier", None)
    session.pop("oauth_state", None)

    # Récupère le pseudo Lichess du compte qu'on vient d'authentifier.
    new_username = None
    try:
        account_resp = requests.get(
            f"{API_BASE}/account",
            headers={"Authorization": f"Bearer {new_access_token}"},
            timeout=10,
        )
        if account_resp.status_code == 200:
            new_username = account_resp.json().get("username")
    except requests.RequestException:
        pass

    if linking_mode:
        # On lie ce compte au compte premium déjà connecté, SANS remplacer
        # la session en cours (le compte principal reste actif).
        primary = session.pop("primary_username", None)
        if primary and new_username and new_username != primary:
            sb = get_supabase()
            if sb:
                try:
                    sb.table("linked_lichess_accounts").upsert({
                        "premium_username": primary,
                        "linked_username": new_username,
                        "access_token": new_access_token,
                    }, on_conflict="premium_username,linked_username").execute()
                except Exception:
                    return redirect(url_for("puzzles", link_error="save_failed"))
        return redirect(url_for("puzzles", linked=new_username or "1"))

    # Connexion normale (compte principal).
    session["access_token"] = new_access_token
    session["lichess_username"] = new_username

    return redirect(url_for("puzzles"))


@app.route("/unlink-account/<linked_username>", methods=["POST"])
def unlink_account(linked_username):
    if "access_token" not in session:
        return redirect(url_for("index"))
    primary = session.get("lichess_username")
    if not is_premium_user(primary):
        return redirect(url_for("puzzles"))

    sb = get_supabase()
    if sb:
        try:
            sb.table("linked_lichess_accounts").delete().eq(
                "premium_username", primary
            ).eq("linked_username", linked_username).execute()
        except Exception:
            pass
    return redirect(url_for("puzzles"))


@app.route("/api/premium/toggle", methods=["POST"])
def api_premium_toggle():
    """Bascule le statut premium de l'utilisateur connecté.
    TEMPORAIRE : en attendant un vrai système de paiement, ce toggle sert
    uniquement à tester le mode premium. À retirer / protéger avant toute
    mise en production réelle avec de vrais utilisateurs."""
    if "access_token" not in session:
        return {"error": "not_authenticated"}, 401

    username = session.get("lichess_username")
    if not username:
        return {"error": "no_username"}, 400

    sb = get_supabase()
    if not sb:
        return {"error": "supabase_unavailable"}, 503

    current = is_premium_user(username)
    try:
        sb.table("premium_users").upsert({
            "lichess_username": username,
            "is_premium": not current,
        }, on_conflict="lichess_username").execute()
    except Exception as exc:
        app.logger.error("Échec toggle premium pour %s : %s", username, exc)
        return {"error": "toggle_failed"}, 500

    return {"premium": not current}


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/coach")
def coach_dashboard():
    """Tableau de bord entraîneur : liste des classes de l'utilisateur
    connecté. Le mode entraîneur ne nécessite pas d'opt-in préalable :
    la ligne `coaches` est créée automatiquement au premier accès."""
    if "access_token" not in session:
        return redirect(url_for("index"))

    username = session.get("lichess_username")
    sb = get_supabase()
    if not sb:
        return render_template("coach.html", error="Supabase non configuré.", classes=[])

    coach_id = get_or_create_coach(username)
    if coach_id is None:
        return render_template("coach.html", error="Impossible d'initialiser le mode entraîneur.", classes=[])

    try:
        resp = (
            sb.table("classes")
            .select("id, name, class_students(count)")
            .eq("coach_id", coach_id)
            .order("created_at")
            .execute()
        )
        classes = [
            {
                "id": row["id"],
                "name": row["name"],
                "student_count": (row.get("class_students") or [{}])[0].get("count", 0),
            }
            for row in (resp.data or [])
        ]
    except Exception as exc:
        app.logger.error("Échec chargement classes pour coach %s : %s", coach_id, exc)
        classes = []

    return render_template("coach.html", classes=classes)


@app.route("/coach/classes", methods=["POST"])
def coach_create_class():
    """Crée une nouvelle classe avec un nom auto-proposé ('Classe N'),
    modifiable ensuite via coach_rename_class."""
    if "access_token" not in session:
        return redirect(url_for("index"))

    username = session.get("lichess_username")
    sb = get_supabase()
    coach_id = get_or_create_coach(username) if sb else None
    if not sb or coach_id is None:
        return redirect(url_for("coach_dashboard"))

    try:
        name = _next_class_name(coach_id, sb)
        sb.table("classes").insert({"coach_id": coach_id, "name": name}).execute()
    except Exception as exc:
        app.logger.error("Échec création classe pour coach %s : %s", coach_id, exc)

    return redirect(url_for("coach_dashboard"))


@app.route("/coach/classes/<int:class_id>", methods=["POST"])
def coach_update_class(class_id):
    """Renomme ou supprime une classe (formulaire HTML classique, pas
    d'API JSON séparée : cohérent avec le style des autres routes du
    projet comme /unlink-account)."""
    if "access_token" not in session:
        return redirect(url_for("index"))

    username = session.get("lichess_username")
    sb = get_supabase()
    coach_id = get_or_create_coach(username) if sb else None
    if not sb or coach_id is None:
        return redirect(url_for("coach_dashboard"))

    action = request.form.get("action")
    try:
        if action == "rename":
            new_name = (request.form.get("name") or "").strip()
            if new_name:
                sb.table("classes").update({"name": new_name}).eq("id", class_id).eq(
                    "coach_id", coach_id
                ).execute()
        elif action == "delete":
            sb.table("classes").delete().eq("id", class_id).eq("coach_id", coach_id).execute()
    except Exception as exc:
        app.logger.error("Échec mise à jour classe %s : %s", class_id, exc)

    return redirect(url_for("coach_dashboard"))


@app.route("/coach/classes/<int:class_id>")
def coach_view_class(class_id):
    """Détail d'une classe : liste des élèves + formulaire d'ajout avec
    autocomplétion (élèves existants + base FIDE en cache local)."""
    if "access_token" not in session:
        return redirect(url_for("index"))

    username = session.get("lichess_username")
    sb = get_supabase()
    coach_id = get_or_create_coach(username) if sb else None
    if not sb or coach_id is None:
        return redirect(url_for("coach_dashboard"))

    try:
        class_resp = (
            sb.table("classes")
            .select("id, name")
            .eq("id", class_id)
            .eq("coach_id", coach_id)
            .limit(1)
            .execute()
        )
        if not class_resp.data:
            return redirect(url_for("coach_dashboard"))
        klass = class_resp.data[0]

        roster_resp = (
            sb.table("class_students")
            .select("student_id, students(id, display_name, fide_id, fide_federation, fide_title, lichess_username, source)")
            .eq("class_id", class_id)
            .execute()
        )
        roster = [row["students"] for row in (roster_resp.data or []) if row.get("students")]
    except Exception as exc:
        app.logger.error("Échec chargement classe %s : %s", class_id, exc)
        return redirect(url_for("coach_dashboard"))

    return render_template("coach_class.html", klass=klass, roster=roster)


@app.route("/api/students/search")
def api_students_search():
    """Autocomplétion : GET /api/students/search?q=car
    Renvoie les élèves déjà créés par l'entraîneur (priorité, évite les
    doublons) puis des correspondances dans le cache local de la base FIDE."""
    if "access_token" not in session:
        return {"error": "not_authenticated"}, 401

    username = session.get("lichess_username")
    coach_id = get_or_create_coach(username)
    if coach_id is None:
        return {"error": "coach_unavailable"}, 503

    query = request.args.get("q", "")
    return jsonify(search_students_autocomplete(coach_id, query))


@app.route("/coach/classes/<int:class_id>/students", methods=["POST"])
def coach_add_student(class_id):
    """Ajoute un élève à une classe. Trois cas, selon les champs du
    formulaire (rempli via l'autocomplétion JS ou saisi manuellement) :
      - student_id fourni       -> élève déjà existant, on lie juste à la classe
      - fide_id fourni (sans id) -> nouvel élève créé depuis une fiche FIDE
      - ni l'un ni l'autre       -> élève purement manuel (nom libre, débutant)
    Le lien Lichess (lichess_username) reste optionnel dans tous les cas."""
    if "access_token" not in session:
        return redirect(url_for("index"))

    username = session.get("lichess_username")
    sb = get_supabase()
    coach_id = get_or_create_coach(username) if sb else None
    if not sb or coach_id is None:
        return redirect(url_for("coach_dashboard"))

    # Vérifie que la classe appartient bien à cet entraîneur.
    class_check = (
        sb.table("classes").select("id").eq("id", class_id).eq("coach_id", coach_id).limit(1).execute()
    )
    if not class_check.data:
        return redirect(url_for("coach_dashboard"))

    student_id = request.form.get("student_id")
    display_name = (request.form.get("name") or "").strip()
    lichess_username = (request.form.get("lichess_username") or "").strip() or None

    try:
        if student_id:
            # Élève déjà existant dans la base de cet entraîneur.
            sb.table("class_students").upsert({
                "class_id": class_id,
                "student_id": int(student_id),
            }, on_conflict="class_id,student_id").execute()
        elif display_name:
            fide_id = request.form.get("fide_id") or None
            new_student = sb.table("students").insert({
                "coach_id": coach_id,
                "display_name": display_name,
                "fide_id": int(fide_id) if fide_id else None,
                "fide_federation": request.form.get("federation") or None,
                "fide_title": request.form.get("title") or None,
                "lichess_username": lichess_username,
                "source": "fide" if fide_id else "manual",
            }).execute()
            if new_student.data:
                sb.table("class_students").insert({
                    "class_id": class_id,
                    "student_id": new_student.data[0]["id"],
                }).execute()
    except Exception as exc:
        app.logger.error("Échec ajout élève à la classe %s : %s", class_id, exc)

    return redirect(url_for("coach_view_class", class_id=class_id))


@app.route("/coach/classes/<int:class_id>/students/<int:student_id>", methods=["POST"])
def coach_remove_student(class_id, student_id):
    """Retire un élève d'une classe (ne supprime pas sa fiche `students`,
    qui peut être partagée par d'autres classes)."""
    if "access_token" not in session:
        return redirect(url_for("index"))

    username = session.get("lichess_username")
    sb = get_supabase()
    coach_id = get_or_create_coach(username) if sb else None
    if not sb or coach_id is None:
        return redirect(url_for("coach_dashboard"))

    try:
        class_check = (
            sb.table("classes").select("id").eq("id", class_id).eq("coach_id", coach_id).limit(1).execute()
        )
        if class_check.data:
            sb.table("class_students").delete().eq("class_id", class_id).eq(
                "student_id", student_id
            ).execute()
    except Exception as exc:
        app.logger.error("Échec retrait élève %s de la classe %s : %s", student_id, class_id, exc)

    return redirect(url_for("coach_view_class", class_id=class_id))


@app.route("/puzzles")
def puzzles():
    access_token = session.get("access_token")
    if not access_token:
        return redirect(url_for("index"))

    primary_username = session.get("lichess_username")
    premium = is_premium_user(primary_username)
    accounts = get_all_accounts_for_session() if premium else [
        {"username": primary_username, "access_token": access_token}
    ]

    import json

    all_failed = []
    session_expired = False
    primary_status = None
    for account in accounts:
        headers = {"Authorization": f"Bearer {account['access_token']}"}
        # On demande un peu de marge (max=200) car l'endpoint ne filtre pas
        # nativement sur "raté uniquement" : le filtrage se fait côté client.
        resp = requests.get(
            f"{API_BASE}/puzzle/activity",
            headers=headers,
            params={"max": 200},
            timeout=20,
            stream=True,
        )
        if account["username"] == primary_username:
            primary_status = resp.status_code
        if resp.status_code == 401:
            if account["username"] == primary_username:
                session_expired = True
            continue  # un compte lié expiré ne doit pas bloquer les autres
        if resp.status_code != 200:
            continue
        for line in resp.iter_lines():
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("win") is False:
                entry["_source_username"] = account["username"]
                all_failed.append(entry)

    if session_expired:
        session.clear()
        return render_template("index.html", error="Session expirée, merci de vous reconnecter."), 401

    if not premium and primary_status not in (200, None):
        return render_template(
            "puzzles.html",
            error=f"Erreur API Lichess ({primary_status})",
            failed=[],
            is_premium=False,
            lichess_username=primary_username,
            linked_accounts=[],
            max_linked_accounts=MAX_LINKED_ACCOUNTS,
            link_error=None,
            linked_username=None,
        )

    # Fusionne et garde les 10 plus récents tous comptes confondus.
    all_failed.sort(key=lambda e: e.get("date", 0), reverse=True)
    failed = all_failed[:10]

    return render_template(
        "puzzles.html",
        failed=failed,
        error=None,
        is_premium=premium,
        lichess_username=primary_username,
        linked_accounts=[a["username"] for a in accounts[1:]] if premium else [],
        max_linked_accounts=MAX_LINKED_ACCOUNTS,
        link_error=request.args.get("link_error"),
        linked_username=request.args.get("linked"),
    )


@app.route("/garden")
def garden():
    """Le jardin de puzzles : vue graphique alternative à la liste, où
    chaque puzzle suivi est une plante dont le stade reflète sa boîte
    Leitner. Les données viennent entièrement du client (localStorage /
    Supabase via sync.js) ; cette route ne fait que servir la page."""
    if "access_token" not in session:
        return redirect(url_for("index"))
    return render_template("garden.html")


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


def _find_puzzle_entry_multi(puzzle_id, accounts):
    """Comme _find_puzzle_entry, mais essaie chaque compte (principal puis
    liés) jusqu'à trouver le puzzle. Renvoie (entry, source_username)."""
    for account in accounts:
        entry = _find_puzzle_entry(puzzle_id, account["access_token"])
        if entry is not None:
            return entry, account["username"]
    return None, None


@app.route("/api/puzzle-info/<puzzle_id>")
def api_puzzle_info(puzzle_id):
    """Endpoint JSON léger : renvoie fen/rating/themes d'un puzzle précis.
    Utilisé côté client pour compléter les puzzles suivis en localStorage
    avant l'ajout de l'aperçu de position (qui n'avaient donc pas de FEN),
    ou tout puzzle sorti de la fenêtre des 200 dernières activités."""
    access_token = session.get("access_token")
    if not access_token:
        return {"error": "not_authenticated"}, 401

    entry, _ = _find_puzzle_entry_multi(puzzle_id, get_all_accounts_for_session())
    if entry is None:
        return {"error": "not_found"}, 404

    puzzle = entry["puzzle"]
    return {
        "id": puzzle_id,
        "fen": puzzle.get("fen"),
        "rating": puzzle.get("rating"),
        "themes": puzzle.get("themes", []),
    }


@app.route("/api/leitner/status")
def api_leitner_status():
    """Indique si l'utilisateur connecté est premium (stockage Supabase
    multi-appareils) ou non (stockage local uniquement)."""
    if "access_token" not in session:
        return {"error": "not_authenticated"}, 401
    username = session.get("lichess_username")
    return {
        "username": username,
        "premium": is_premium_user(username),
    }


def _require_premium():
    """Renvoie (username, None) si OK, sinon (None, (response, status))."""
    if "access_token" not in session:
        return None, ({"error": "not_authenticated"}, 401)
    username = session.get("lichess_username")
    if not is_premium_user(username):
        return None, ({"error": "not_premium"}, 403)
    sb = get_supabase()
    if not sb:
        return None, ({"error": "supabase_unavailable"}, 503)
    return username, None


@app.route("/api/leitner/data")
def api_leitner_data():
    """Renvoie tout le suivi Leitner de l'utilisateur premium, au même
    format que le localStorage côté client (objet clé = puzzle_id)."""
    username, err = _require_premium()
    if err:
        return err

    sb = get_supabase()
    resp = sb.table("leitner_progress").select("*").eq("lichess_username", username).execute()

    data = {}
    for row in resp.data or []:
        data[row["puzzle_id"]] = {
            "box": row["box"],
            "nextReview": row["next_review"],
            "rating": row.get("rating"),
            "themes": row.get("themes") or [],
            "fen": row.get("fen"),
        }
    return {"data": data}


@app.route("/api/leitner/track", methods=["POST"])
def api_leitner_track():
    """Équivalent premium de leitnerTrackFailedPuzzle() : ajoute un puzzle
    raté s'il n'existe pas déjà (ne l'écrase pas s'il existe)."""
    username, err = _require_premium()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    puzzle_id = body.get("puzzle_id")
    if not puzzle_id:
        return {"error": "missing_puzzle_id"}, 400

    sb = get_supabase()
    existing = (
        sb.table("leitner_progress")
        .select("puzzle_id")
        .eq("lichess_username", username)
        .eq("puzzle_id", puzzle_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        return {"status": "already_tracked"}

    sb.table("leitner_progress").insert({
        "lichess_username": username,
        "puzzle_id": puzzle_id,
        "box": 1,
        "next_review": _leitner_next_review(1),
        "rating": body.get("rating"),
        "themes": body.get("themes") or [],
        "fen": body.get("fen"),
    }).execute()
    return {"status": "tracked"}


@app.route("/api/leitner/record", methods=["POST"])
def api_leitner_record():
    """Équivalent premium de leitnerRecordResult() : met à jour la boîte et
    la prochaine révision selon la réussite ou non."""
    username, err = _require_premium()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    puzzle_id = body.get("puzzle_id")
    success = bool(body.get("success"))
    if not puzzle_id:
        return {"error": "missing_puzzle_id"}, 400

    sb = get_supabase()
    existing = (
        sb.table("leitner_progress")
        .select("box")
        .eq("lichess_username", username)
        .eq("puzzle_id", puzzle_id)
        .limit(1)
        .execute()
    )
    current_box = existing.data[0]["box"] if existing.data else 1
    new_box = min(current_box + 1, LEITNER_MAX_BOX) if success else 1

    sb.table("leitner_progress").upsert({
        "lichess_username": username,
        "puzzle_id": puzzle_id,
        "box": new_box,
        "next_review": _leitner_next_review(new_box),
        "rating": body.get("rating"),
        "themes": body.get("themes") or [],
        "fen": body.get("fen"),
    }, on_conflict="lichess_username,puzzle_id").execute()

    return {"status": "recorded", "box": new_box}


@app.route("/api/leitner/set-fen", methods=["POST"])
def api_leitner_set_fen():
    """Complète le FEN d'un puzzle déjà suivi (rattrapage aperçu manquant)."""
    username, err = _require_premium()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    puzzle_id = body.get("puzzle_id")
    fen = body.get("fen")
    if not puzzle_id or not fen:
        return {"error": "missing_fields"}, 400

    sb = get_supabase()
    sb.table("leitner_progress").update({"fen": fen}).eq(
        "lichess_username", username
    ).eq("puzzle_id", puzzle_id).execute()
    return {"status": "updated"}


@app.route("/api/leitner/push", methods=["POST"])
def api_leitner_push():
    """Envoie vers Supabase des entrées locales telles quelles (box et
    next_review préservés, PAS réinitialisés) — utilisé lors du passage en
    premium pour faire remonter l'historique local existant sans le perdre."""
    username, err = _require_premium()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    entries = body.get("entries") or {}
    if not isinstance(entries, dict):
        return {"error": "invalid_entries"}, 400

    sb = get_supabase()
    rows = []
    for puzzle_id, e in entries.items():
        if not isinstance(e, dict):
            continue
        rows.append({
            "lichess_username": username,
            "puzzle_id": puzzle_id,
            "box": e.get("box", 1),
            "next_review": e.get("nextReview") or _leitner_next_review(1),
            "rating": e.get("rating"),
            "themes": e.get("themes") or [],
            "fen": e.get("fen"),
        })

    if rows:
        try:
            sb.table("leitner_progress").upsert(
                rows, on_conflict="lichess_username,puzzle_id"
            ).execute()
        except Exception as exc:
            app.logger.error("Échec push leitner en masse pour %s : %s", username, exc)
            return {"error": "push_failed"}, 500

    return {"status": "pushed", "count": len(rows)}


@app.route("/replay/<puzzle_id>")
def replay(puzzle_id):
    access_token = session.get("access_token")
    if not access_token:
        return redirect(url_for("index"))

    target, source_username = _find_puzzle_entry_multi(puzzle_id, get_all_accounts_for_session())

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
        is_premium=is_premium_user(session.get("lichess_username")),
        lichess_username=session.get("lichess_username"),
        source_username=source_username,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
