-- Second half of the isolation, run as the `directory` role against its own
-- database. Separate from isolate_directory_role.sql because once ownership has
-- moved, the crawler's role can no longer alter these privileges — attempting it
-- there produces a warning rather than an error, which is easy to miss.
--
-- Idempotent: safe to rerun.

\set ON_ERROR_STOP on

REVOKE CONNECT ON DATABASE directory FROM PUBLIC;

\echo ''
\echo 'directory database access list (PUBLIC should hold =T only, no c):'
SELECT datname, array_to_string(datacl, ' , ') AS acl
FROM pg_database WHERE datname = 'directory';
