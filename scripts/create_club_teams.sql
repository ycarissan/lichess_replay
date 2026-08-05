-- ============================================================================
-- Mode manager / capitaine : clubs, équipes, joueurs, effectifs, compositions.
--
-- Un manager gère un club. Un club a un catalogue de types d'équipe
-- (nom + nombre de joueurs requis par match, ex. "Nationale 1" -> 8), un
-- vivier de joueurs, et des équipes (chacune d'un type donné, avec un
-- capitaine et un effectif). Le capitaine compose, pour une ronde donnée
-- d'une compétition, une liste de joueurs tirée de l'effectif de son
-- équipe (une "composition").
--
-- Idempotent : peut être ré-exécuté sans risque.
-- ============================================================================

-- --- Identité manager --------------------------------------------------------
create table if not exists clubs (
    id          bigint generated always as identity primary key,
    name        text not null,
    created_at  timestamptz not null default now()
);

-- Un manager peut se connecter via Lichess OU email (comme les coachs).
create table if not exists managers (
    id                bigint generated always as identity primary key,
    club_id           bigint references clubs(id) on delete cascade,
    lichess_username  text,
    email             text,
    display_name      text,
    created_at        timestamptz not null default now()
);

create unique index if not exists idx_managers_lichess_unique
    on managers (lichess_username) where lichess_username is not null;
create unique index if not exists idx_managers_email_unique
    on managers (email) where email is not null;

alter table managers drop constraint if exists managers_identity_present;
alter table managers
    add constraint managers_identity_present
    check (lichess_username is not null or email is not null);

-- --- Types d'équipe (catalogue par club, pré-rempli + éditable) -------------
create table if not exists team_types (
    id            bigint generated always as identity primary key,
    club_id       bigint not null references clubs(id) on delete cascade,
    name          text not null,
    board_count   integer not null check (board_count > 0),
    created_at    timestamptz not null default now()
);

create index if not exists idx_team_types_club on team_types(club_id);

-- --- Joueurs du club (vivier, indépendant des élèves du mode entraîneur,
--     mais peut recouper les mêmes personnes : même fide_id/lichess_username) --
create table if not exists players (
    id                bigint generated always as identity primary key,
    club_id           bigint not null references clubs(id) on delete cascade,
    display_name      text not null,
    display_name_lower text generated always as (lower(display_name)) stored,
    fide_id           bigint,
    fide_federation   text,
    fide_title        text,
    lichess_username  text,
    source            text not null default 'manual' check (source in ('fide', 'manual')),
    created_at        timestamptz not null default now()
);

create index if not exists idx_players_club on players(club_id);
create index if not exists idx_players_display_name_lower_prefix
    on players (club_id, display_name_lower text_pattern_ops);

-- --- Identité capitaine (Lichess ou email, comme manager/coach) -------------
-- Un capitaine EST GÉNÉRALEMENT aussi un joueur de l'équipe, d'où le lien
-- optionnel vers players(id) — mais son identité de connexion (Lichess ou
-- email) est stockée séparément, car un joueur ne se connecte pas
-- forcément lui-même à l'application.
create table if not exists captains (
    id                bigint generated always as identity primary key,
    club_id           bigint not null references clubs(id) on delete cascade,
    player_id         bigint references players(id) on delete set null,
    lichess_username  text,
    email             text,
    display_name      text,
    created_at        timestamptz not null default now()
);

create unique index if not exists idx_captains_lichess_unique
    on captains (lichess_username) where lichess_username is not null;
create unique index if not exists idx_captains_email_unique
    on captains (email) where email is not null;

alter table captains drop constraint if exists captains_identity_present;
alter table captains
    add constraint captains_identity_present
    check (lichess_username is not null or email is not null);

-- --- Équipes -----------------------------------------------------------------
create table if not exists teams (
    id            bigint generated always as identity primary key,
    club_id       bigint not null references clubs(id) on delete cascade,
    team_type_id  bigint not null references team_types(id),
    captain_id    bigint references captains(id) on delete set null,
    name          text not null,
    created_at    timestamptz not null default now()
);

create index if not exists idx_teams_club on teams(club_id);
create index if not exists idx_teams_captain on teams(captain_id);

-- --- Effectif d'une équipe (joueurs attribués par le manager) --------------
create table if not exists team_squad (
    team_id     bigint not null references teams(id) on delete cascade,
    player_id   bigint not null references players(id) on delete cascade,
    added_at    timestamptz not null default now(),
    primary key (team_id, player_id)
);

-- --- Compositions par ronde (le capitaine choisit dans l'effectif) --------
create table if not exists team_lineups (
    id            bigint generated always as identity primary key,
    team_id       bigint not null references teams(id) on delete cascade,
    round_number  integer not null,
    round_label   text,          -- ex. "Ronde 2 - Nationale 6" (libre, optionnel)
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create unique index if not exists idx_team_lineups_team_round
    on team_lineups (team_id, round_number);

create table if not exists lineup_players (
    lineup_id     bigint not null references team_lineups(id) on delete cascade,
    board_number  integer not null check (board_number > 0),
    player_id     bigint not null references players(id) on delete cascade,
    primary key (lineup_id, board_number),
    unique (lineup_id, player_id)
);

-- --- RLS : accès uniquement via la clé service_role côté serveur Flask ------
alter table clubs enable row level security;
alter table managers enable row level security;
alter table team_types enable row level security;
alter table players enable row level security;
alter table captains enable row level security;
alter table teams enable row level security;
alter table team_squad enable row level security;
alter table team_lineups enable row level security;
alter table lineup_players enable row level security;
