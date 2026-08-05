-- ============================================================================
-- Optimisation de la recherche par préfixe (autocomplétion élèves).
--
-- Problème : l'index créé initialement (idx_fide_players_name_lower sur
-- lower(name)) n'était en réalité jamais utilisé, car la requête de
-- l'application filtre avec `name ILIKE 'q%'` (sur la colonne brute, casse
-- d'origine) — une expression différente de celle indexée. PostgreSQL
-- retombait donc sur un scan séquentiel des ~500 000 lignes de fide_players
-- à chaque frappe clavier, d'où la lenteur ressentie.
--
-- Correctif : une colonne générée en minuscule (name_lower), indexée avec
-- text_pattern_ops (le bon type d'index pour un préfixe LIKE 'xxx%', quelle
-- que soit la locale de la base). La requête compare ensuite
-- name_lower LIKE lower(q)||'%', qui EXPLOIT réellement cet index.
--
-- Idempotent : peut être ré-exécuté sans risque.
-- ============================================================================

-- --- fide_players -----------------------------------------------------------
alter table fide_players
    add column if not exists name_lower text generated always as (lower(name)) stored;

create index if not exists idx_fide_players_name_lower_prefix
    on fide_players (name_lower text_pattern_ops);

-- Ancien index inutilisé par la requête réelle de l'application : supprimé.
drop index if exists idx_fide_players_name_lower;

-- --- students (recherche parmi les élèves déjà créés par l'entraîneur) ------
alter table students
    add column if not exists display_name_lower text generated always as (lower(display_name)) stored;

create index if not exists idx_students_display_name_lower_prefix
    on students (coach_id, display_name_lower text_pattern_ops);
