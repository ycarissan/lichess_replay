-- ============================================================================
-- Rôle "sayen" : super-administrateur, au-dessus de tous les autres rôles.
--
-- IMPORTANT — contrairement à coaches/managers/captains, cette table N'EST
-- JAMAIS remplie automatiquement par l'application (pas d'auto-création au
-- premier accès). Un sayen ne peut être créé que manuellement, ici, par
-- vous : remplacez la valeur ci-dessous par votre pseudo Lichess ou votre
-- email, puis exécutez cette section séparément.
--
-- Idempotent (hors insertion manuelle) : peut être ré-exécuté sans risque.
-- ============================================================================

create table if not exists sayens (
    id                bigint generated always as identity primary key,
    lichess_username  text,
    email             text,
    display_name      text,
    created_at        timestamptz not null default now()
);

create unique index if not exists idx_sayens_lichess_unique
    on sayens (lichess_username) where lichess_username is not null;
create unique index if not exists idx_sayens_email_unique
    on sayens (email) where email is not null;

alter table sayens drop constraint if exists sayens_identity_present;
alter table sayens
    add constraint sayens_identity_present
    check (lichess_username is not null or email is not null);

alter table sayens enable row level security;

-- ----------------------------------------------------------------------------
-- ÉTAPE MANUELLE — à exécuter séparément avec VOTRE identité :
--
--   insert into sayens (lichess_username, display_name)
--   values ('hdaverc34', 'Yannick');
--
-- ou, pour une connexion par email :
--
--   insert into sayens (email, display_name)
--   values ('votre@email.com', 'Yannick');
-- ----------------------------------------------------------------------------
