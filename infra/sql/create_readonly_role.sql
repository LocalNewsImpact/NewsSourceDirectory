-- A read-only role for publishing the feed.
--
-- The QA workflow reads the registry from a GitHub runner. Giving it the
-- read-write role would mean a mistake in a workflow file could alter curated
-- data; this role can only SELECT, enforced by Postgres rather than by our care.
--
-- Two connections are needed and the order matters:
--
--   1. As mizzou_user (a cloudsqlsuperuser) to create the role — role creation
--      is cluster-wide, and `directory` lost that right when it was stripped of
--      cloudsqlsuperuser.
--   2. As `directory`, which owns the database, to grant privileges inside it
--      (grant_readonly.sql).
--
-- The password is passed as :pw. It is set with a plain statement rather than
-- inside a DO block, because psql substitutes variables client-side and never
-- looks inside a dollar-quoted string.

\set ON_ERROR_STOP on

CREATE ROLE directory_ro LOGIN PASSWORD :'pw';

-- Deny everything by default; grant_readonly.sql adds the only access it gets.
REVOKE ALL ON DATABASE directory FROM directory_ro;
