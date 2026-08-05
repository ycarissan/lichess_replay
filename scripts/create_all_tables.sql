-- ============================================================
-- Crée toutes les tables du projet si elles n'existent pas déjà
-- (sans danger de ré-exécution : IF NOT EXISTS partout).
-- Coller tel quel dans Supabase -> SQL Editor -> Run.
-- ============================================================

create table if not exists replayed_puzzles (
  id bigint generated always as identity primary key,
  puzzle_id text not null,
  rating int,
  created_at timestamptz default now()
);
alter table replayed_puzzles enable row level security;

create table if not exists premium_users (
  lichess_username text primary key,
  is_premium boolean not null default true,
  created_at timestamptz not null default now()
);
alter table premium_users enable row level security;

create table if not exists leitner_progress (
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

create table if not exists linked_lichess_accounts (
  id bigint generated always as identity primary key,
  premium_username text not null,
  linked_username text not null,
  access_token text not null,
  created_at timestamptz not null default now(),
  unique (premium_username, linked_username)
);
alter table linked_lichess_accounts enable row level security;

-- Vérification finale : les 4 tables doivent maintenant apparaître ici.
select table_name from information_schema.tables
where table_schema = 'public'
  and table_name in ('replayed_puzzles', 'premium_users', 'leitner_progress', 'linked_lichess_accounts')
order by table_name;
