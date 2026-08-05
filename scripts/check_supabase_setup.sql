-- ============================================================
-- Diagnostic : vérifie que les 4 tables attendues existent,
-- avec leurs colonnes et le statut RLS.
-- Coller tel quel dans Supabase -> SQL Editor -> Run.
-- ============================================================

-- 1) Quelles tables attendues existent réellement ?
select
  t.table_name,
  case when t.table_name is not null then '✅ existe' else '❌ manquante' end as statut
from (
  values
    ('replayed_puzzles'),
    ('premium_users'),
    ('leitner_progress'),
    ('linked_lichess_accounts')
) as expected(table_name)
left join information_schema.tables t
  on t.table_schema = 'public' and t.table_name = expected.table_name;

-- 2) Pour les tables qui existent : RLS est-il activé ?
select
  c.relname as table_name,
  case when c.relrowsecurity then '✅ RLS activé' else '⚠️ RLS DÉSACTIVÉ' end as rls_status
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relname in ('replayed_puzzles', 'premium_users', 'leitner_progress', 'linked_lichess_accounts');

-- 3) Détail des colonnes de chaque table existante (pour repérer un
--    écart de schéma : colonne manquante, mauvais type, etc.)
select
  table_name,
  column_name,
  data_type,
  is_nullable
from information_schema.columns
where table_schema = 'public'
  and table_name in ('replayed_puzzles', 'premium_users', 'leitner_progress', 'linked_lichess_accounts')
order by table_name, ordinal_position;

-- 4) Contraintes uniques / clés primaires (nécessaires pour que les
--    upsert on_conflict fonctionnent correctement)
select
  tc.table_name,
  tc.constraint_type,
  string_agg(kcu.column_name, ', ' order by kcu.ordinal_position) as colonnes
from information_schema.table_constraints tc
join information_schema.key_column_usage kcu
  on tc.constraint_name = kcu.constraint_name and tc.table_schema = kcu.table_schema
where tc.table_schema = 'public'
  and tc.table_name in ('replayed_puzzles', 'premium_users', 'leitner_progress', 'linked_lichess_accounts')
  and tc.constraint_type in ('PRIMARY KEY', 'UNIQUE')
group by tc.table_name, tc.constraint_type;

-- 5) Contenu actuel de premium_users (pratique pour vérifier votre
--    propre statut sans repasser par l'app).
--    ⚠️ Ne fonctionne QUE si la table existe déjà (voir résultat de la
--    requête 1 ci-dessus). Si elle manque encore, commentez cette ligne
--    ou exécutez-la séparément après avoir créé la table.
select * from premium_users;
