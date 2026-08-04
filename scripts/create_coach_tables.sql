-- ============================================================================
-- Mode entraîneur : classes, élèves, cache local de la base FIDE
-- Idempotent (IF NOT EXISTS) : peut être ré-exécuté sans risque.
-- ============================================================================

-- Un entraîneur est un utilisateur Lichess ayant activé le mode entraîneur.
create table if not exists coaches (
    id              bigint generated always as identity primary key,
    lichess_username text not null unique,
    display_name    text,
    created_at      timestamptz not null default now()
);

-- Un élève : peut venir de la base FIDE (fide_id renseigné), être lié à un
-- compte Lichess (optionnel, cf. décision produit), ou être purement manuel
-- (débutant sans FIDE ni Lichess, juste un nom).
create table if not exists students (
    id                bigint generated always as identity primary key,
    coach_id          bigint not null references coaches(id) on delete cascade,
    display_name      text not null,
    fide_id           bigint,              -- nullable : élève non licencié FIDE
    fide_federation   text,
    fide_title        text,
    fide_birth_year   integer,
    lichess_username  text,                -- nullable : lien optionnel
    source            text not null default 'manual' check (source in ('fide', 'manual')),
    created_at        timestamptz not null default now()
);

create index if not exists idx_students_coach on students(coach_id);
create index if not exists idx_students_lichess on students(lower(lichess_username));

-- Une classe appartient à un entraîneur. Nom auto-proposé "Classe N",
-- modifiable ensuite par l'entraîneur (colonne libre, pas de contrainte de
-- format une fois créée).
create table if not exists classes (
    id          bigint generated always as identity primary key,
    coach_id    bigint not null references coaches(id) on delete cascade,
    name        text not null,
    created_at  timestamptz not null default now()
);

create index if not exists idx_classes_coach on classes(coach_id);

-- Relation many-to-many classe <-> élève (un élève peut appartenir à
-- plusieurs classes du même entraîneur).
create table if not exists class_students (
    class_id    bigint not null references classes(id) on delete cascade,
    student_id  bigint not null references students(id) on delete cascade,
    added_at    timestamptz not null default now(),
    primary key (class_id, student_id)
);

-- ----------------------------------------------------------------------------
-- Cache local de la base FIDE (import périodique, voir
-- scripts/import_fide_players.py). Évite d'interroger un service externe à
-- chaque frappe clavier lors de l'autocomplétion.
-- ----------------------------------------------------------------------------
create table if not exists fide_players (
    fide_id       bigint primary key,
    name          text not null,          -- format FIDE : "Nom, Prénom"
    federation    text,
    sex           text,
    title         text,
    standard_rating integer,
    rapid_rating  integer,
    blitz_rating  integer,
    birth_year    integer,
    updated_at    timestamptz not null default now()
);

-- Recherche par préfixe insensible à la casse (l'entraîneur tape le début
-- du nom de famille, format FIDE "Nom, Prénom").
create index if not exists idx_fide_players_name_lower on fide_players (lower(name) text_pattern_ops);

-- Sécurité : RLS activé, accès uniquement via la clé service_role côté
-- serveur Flask (même politique que les autres tables du projet).
alter table coaches enable row level security;
alter table students enable row level security;
alter table classes enable row level security;
alter table class_students enable row level security;
alter table fide_players enable row level security;
