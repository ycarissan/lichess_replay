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

## Système premium (stockage multi-appareils via Supabase)

Architecture à deux niveaux :

| | Gratuit | Premium |
|---|---|---|
| Stockage du suivi Leitner | `localStorage` (navigateur uniquement) | Supabase (synchronisé sur tous les appareils) |
| Reconnexion sur un autre appareil | Historique reparti de zéro | Historique retrouvé automatiquement |

**Aucun système de paiement n'est implémenté ici** — seule la couche de données est prête. Le statut premium est déterminé par la présence (et `is_premium = true`) d'une ligne dans la table `premium_users`, que vous ajoutez manuellement pour l'instant (ou via un futur webhook Stripe/autre, à brancher séparément).

### Tables SQL à créer (en plus de `replayed_puzzles`)

```sql
create table premium_users (
  lichess_username text primary key,
  is_premium boolean not null default true,
  created_at timestamptz not null default now()
);
alter table premium_users enable row level security;

create table leitner_progress (
  id bigint generated always as identity primary key,
  lichess_username text not null,
  puzzle_id text not null,
  box int not null default 1,
  next_review timestamptz not null default now(),
  rating int,
  themes text[],
  fen text,
  updated_at timestamptz not null default now(),
  unique (lichess_username, puzzle_id)
);
alter table leitner_progress enable row level security;
```

RLS activé sans policy : seule la clé secrète/`service_role` (utilisée par le serveur Flask) peut y accéder, ce qui est le comportement voulu.

### Accorder le statut premium à un utilisateur

Dans **Table Editor → premium_users**, ajoutez une ligne :
```sql
insert into premium_users (lichess_username, is_premium) values ('VotrePseudoLichess', true);
```

### Comment ça fonctionne côté app

- `GET /api/leitner/status` : indique si l'utilisateur connecté est premium.
- Si premium : au chargement de `/puzzles` et `/replay/<id>`, les données Supabase sont rapatriées et **remplacent** le cache local (Supabase fait autorité). Chaque nouvelle action (puzzle raté détecté, résolution, échec) est ensuite écrite à la fois en local (rapidité d'affichage) et sur Supabase (synchro).
- Si gratuit : comportement inchangé, 100% `localStorage`.

### Comptes Lichess multiples (premium, jusqu'à 4)

```sql
create table linked_lichess_accounts (
  id bigint generated always as identity primary key,
  premium_username text not null,
  linked_username text not null,
  access_token text not null,
  created_at timestamptz not null default now(),
  unique (premium_username, linked_username)
);
alter table linked_lichess_accounts enable row level security;
```

⚠️ Cette table contient des **tokens d'accès Lichess** (mêmes privilèges que
le token de session : lecture de l'activité de puzzles). RLS + clé secrète
uniquement protège l'accès réseau, mais les tokens sont stockés en clair
dans la base — acceptable pour ce projet, mais à chiffrer si vous passez en
production sérieuse.

Un utilisateur premium peut lier jusqu'à `MAX_LINKED_ACCOUNTS` (4 par
défaut, modifiable dans `app.py`) comptes Lichess. Les 10 derniers puzzles
ratés affichés sont fusionnés et triés par date sur l'ensemble des comptes
liés, avec une étiquette indiquant le compte d'origine sur chaque carte.

## Limites connues



- Le token est gardé en session Flask (cookie signé) — convient pour un
  usage local/personnel, pas pour de la production multi-utilisateurs sans
  durcissement (HTTPS, stockage serveur du token, expiration, etc.).
- L'endpoint `/api/puzzle/activity` ne propose pas de filtre serveur natif
  sur "ratés uniquement" : le filtrage se fait côté application après
  téléchargement d'un lot d'entrées (`max=200`, ajustable si besoin).
- La solution est simplement rejouée pas à pas ; il n'y a pas de validation
  d'un coup joué par l'utilisateur (pas de "essayez vous-même").
