-- Part 2, run as `directory` against the directory database.
--
-- ALTER DEFAULT PRIVILEGES matters as much as the grants: without it a table
-- added by a future migration would be invisible to the publisher, and the feed
-- would quietly lose a column rather than fail.

\set ON_ERROR_STOP on

GRANT CONNECT ON DATABASE directory TO directory_ro;
GRANT USAGE ON SCHEMA public TO directory_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO directory_ro;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO directory_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO directory_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO directory_ro;

\echo ''
\echo 'privileges held by directory_ro (expect SELECT and nothing else):'
SELECT DISTINCT privilege_type
FROM information_schema.table_privileges
WHERE grantee = 'directory_ro'
ORDER BY privilege_type;
