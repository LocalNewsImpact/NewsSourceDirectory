# Security

## Reporting

Email **chair@localnewsimpact.org**. Do not open a public issue for anything
that exposes data or credentials.

The registry holds no personal data beyond the names and addresses of newsrooms,
and the public feed is published deliberately. The things worth reporting
urgently are: a way to reach the database or the admin without a
`@localnewsimpact.org` account, a credential committed to the repository, or
private data appearing in the public feed.

## What protects what

The admin is authenticated with Google sign-in restricted to the
`localnewsimpact.org` hosted domain, verified server-side rather than trusted
from the `hd` parameter. See [docs/auth.md](docs/auth.md).

The public feed is static and content-addressed. It is built from an allowlist of
fields, and CI fails if a payload carries a column that is not on it, so a new
model field cannot leak into the public directory by being added.

The database is reachable only over the Cloud SQL socket by the service account
the admin runs as. The `directory` role owns its own database, holds no role
memberships, and cannot connect to the crawler's database on the same instance.

## Credentials

`.env` is gitignored and `.env.example` carries no real values. Production
secrets live in Secret Manager and reach the container as environment variables;
they are never assembled into a `DATABASE_URL` or passed on a deploy command
line. If a credential does reach a commit, treat it as public: rotate it first,
then rewrite history if it is worth doing.
