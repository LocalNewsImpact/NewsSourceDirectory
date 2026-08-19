-- Isolate the directory role from the crawler's database.
--
-- Two problems, both defaults rather than mistakes:
--
--   1. Postgres grants CONNECT on every database to PUBLIC, so the `directory`
--      role could open the crawler's `mizzou` database. Verified, not assumed.
--   2. Cloud SQL adds every API-created user to `cloudsqlsuperuser`. That is the
--      larger hole: membership confers rights over the whole instance, so
--      revoking CONNECT alone would not have closed anything.
--
-- Order matters. Ownership is granted before privileges are removed, so the
-- directory role never loses the ability to run its own migrations.
--
-- Idempotent: safe to rerun.
--
--   ./infra/sql/apply.sh

\set ON_ERROR_STOP on
BEGIN;

-- 1. The directory role must own its own database before it stops being a
--    superuser, or migrations lose the right to create tables.
--
--    Transferring ownership requires the current owner to be a member of the
--    incoming one, which shared membership of cloudsqlsuperuser does not confer.
--    So the membership is granted, used, and given straight back.
GRANT directory TO mizzou_user;
ALTER DATABASE directory OWNER TO directory;
REVOKE directory FROM mizzou_user;

-- The schema inside it too, or migrations can create nothing.
GRANT ALL ON SCHEMA public TO directory;

-- 2. Close the crawler's database to everything that does not need it.
--    Grant first, revoke second — the reverse order locks out the crawler.
GRANT CONNECT ON DATABASE mizzou TO mizzou_user;
GRANT CONNECT ON DATABASE mizzou TO datastream_user;
REVOKE CONNECT ON DATABASE mizzou FROM PUBLIC;

-- The mirror-image lock on the directory database cannot run here: once
-- ownership moves, this connection is no longer entitled to change it. It lives
-- in harden_directory_db.sql, which apply.sh runs next as the directory role.

-- 4. Remove the escalation path. Without this the two revokes above are theatre:
--    a member of cloudsqlsuperuser can SET ROLE and undo them.
REVOKE cloudsqlsuperuser FROM directory;

COMMIT;

-- Verification. datacl should now list explicit grants rather than being null,
-- and directory should hold no role memberships.
\echo ''
\echo 'database access lists:'
SELECT datname, coalesce(array_to_string(datacl, ' , '), '(default: PUBLIC may connect)') AS acl
FROM pg_database WHERE datname IN ('mizzou', 'directory') ORDER BY datname;

\echo ''
\echo 'role memberships for directory (expected: none):'
SELECT g.rolname AS member_of
FROM pg_auth_members m
JOIN pg_roles r ON r.oid = m.member
JOIN pg_roles g ON g.oid = m.roleid
WHERE r.rolname = 'directory';
