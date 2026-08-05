-- ============================================================================
-- Authentification par email (magic link Supabase Auth) pour le mode
-- entraîneur / premium, en complément de la connexion Lichess existante.
--
-- Un coach peut désormais être identifié par lichess_username OU par email
-- (au moins l'un des deux doit être renseigné). Idempotent.
-- ============================================================================

alter table coaches alter column lichess_username drop not null;

alter table coaches
    add column if not exists email text;

create unique index if not exists idx_coaches_email_unique
    on coaches (email) where email is not null;

alter table coaches drop constraint if exists coaches_identity_present;
alter table coaches
    add constraint coaches_identity_present
    check (lichess_username is not null or email is not null);
