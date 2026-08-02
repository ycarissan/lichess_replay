# Lichess — Puzzles ratés (replay)

Site Flask permettant de se connecter à Lichess (OAuth2 + PKCE, sans mot de
passe ni secret partagé) et de rejouer les **10 derniers puzzles ratés** de
l'utilisateur authentifié.

## Installation

```bash
python3 -m venv venv
source venv/bin/activate      # Windows : venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Aucun enregistrement préalable d'app n'est requis chez Lichess : le flux
OAuth2 PKCE public accepte un `client_id` arbitraire. Il suffit qu'il reste
constant pour votre app.

Variables d'environnement optionnelles (valeurs par défaut adaptées à un
usage local) :

```bash
export LICHESS_CLIENT_ID="mon-app-puzzle-replay"
export LICHESS_REDIRECT_URI="http://localhost:5000/callback"
export FLASK_SECRET_KEY="une-valeur-aleatoire-longue"
```

⚠️ Si vous changez `LICHESS_REDIRECT_URI`, l'URL doit être strictement
identique à celle utilisée dans le navigateur (schéma, host, port, chemin).

## Lancement

```bash
python app.py
```

Puis ouvrez http://localhost:5000, cliquez sur **"Se connecter avec
Lichess"**, autorisez le scope `puzzle:read`, et vous accédez à la liste de
vos 10 derniers puzzles ratés, cliquables pour les rejouer coup par coup.

## Comment ça marche

1. **`/login`** génère une paire PKCE (`code_verifier` / `code_challenge`)
   et redirige vers `https://lichess.org/oauth`.
2. **`/callback`** échange le code d'autorisation contre un `access_token`
   via `POST https://lichess.org/api/token` (pas de client secret : flux
   public PKCE).
3. **`/puzzles`** interroge `GET /api/puzzle/activity?max=200` (endpoint
   OAuth, scope `puzzle:read`), filtre les entrées où `win == false`, et
   garde les 10 premières (l'API trie déjà du plus récent au plus ancien).
4. **`/replay/<id>`** récupère la position de départ (`fen`) et les coups
   de la solution (`solution`, en notation UCI) et les rejoue sur un
   échiquier `chessboard.js` piloté par `chess.js`.

## Déploiement sur Render (déploiement auto depuis GitHub)

1. Poussez ce projet sur un dépôt GitHub.
2. Sur [render.com](https://render.com), créez un compte puis
   **New → Blueprint**, et pointez vers votre dépôt. Render détecte
   automatiquement `render.yaml` et configure le service.
3. Dans le dashboard du service, onglet **Environment**, renseignez si besoin
   `SUPABASE_URL` et `SUPABASE_KEY` (jamais dans le repo).
4. Une fois déployé, notez l'URL publique (ex.
   `https://lichess-puzzle-replay.onrender.com`) et mettez-la à jour dans
   `render.yaml` (`LICHESS_REDIRECT_URI`) puis repoussez sur GitHub.
5. **Déploiement continu** : `autoDeploy: true` dans `render.yaml` signifie
   que chaque `git push` sur `main` redéploie automatiquement le site — rien
   d'autre à faire.

Note : le plan gratuit de Render met le service en veille après 15 min
d'inactivité (le premier appel après veille prend ~1 min). Passez sur un plan
payant pour supprimer cette latence.

## Connexion à Supabase (optionnelle)

Le module `supabase_client.py` fournit un client prêt à l'emploi, activé
uniquement si `SUPABASE_URL` et `SUPABASE_KEY` sont définis (sinon l'app
fonctionne normalement sans Supabase, aucune erreur).

Exemple d'utilisation déjà branché dans `app.py` : chaque replay de puzzle
est journalisé dans une table `replayed_puzzles` si Supabase est configuré.
Pour l'activer :

1. Créez un projet sur [supabase.com](https://supabase.com).
2. Dans **Project Settings → API**, récupérez `Project URL` (→
   `SUPABASE_URL`) et `anon public key` (→ `SUPABASE_KEY`).
3. Créez la table (SQL editor Supabase) :

   ```sql
   create table replayed_puzzles (
     id bigint generated always as identity primary key,
     puzzle_id text not null,
     rating int,
     created_at timestamptz default now()
   );
   ```

4. Ajoutez `SUPABASE_URL` et `SUPABASE_KEY` dans les variables d'environnement
   de Render (jamais en dur dans le code ni commit dans Git).

## Limites connues

- Le token est gardé en session Flask (cookie signé) — convient pour un
  usage local/personnel, pas pour de la production multi-utilisateurs sans
  durcissement (HTTPS, stockage serveur du token, expiration, etc.).
- L'endpoint `/api/puzzle/activity` ne propose pas de filtre serveur natif
  sur "ratés uniquement" : le filtrage se fait côté application après
  téléchargement d'un lot d'entrées (`max=200`, ajustable si besoin).
- La solution est simplement rejouée pas à pas ; il n'y a pas de validation
  d'un coup joué par l'utilisateur (pas de "essayez vous-même").
