# Infrastructure

`bootstrap.sh` is the description of the project. Every stage checks before it
creates, so rerunning is safe and reading it tells you what exists.

```bash
./infra/bootstrap.sh                  # everything, including the database
./infra/bootstrap.sh sql              # just the database and its grant
./infra/bootstrap.sh lb_ip lb         # fallback only — see "Admin hostname"
```

## Running a management command against production

```bash
./infra/manage.sh <command> [args...]
```

Uses the image the service is currently running, so there is no risk of
executing code that is not deployed.

## What exists

| | |
|---|---|
| Project | `lnic-source-directory` (666766099662), org `localnewsimpact.org` |
| Region | `us-central1` |
| Feed bucket | `gs://lnic-source-directory-feed` — **not yet public, see below** |
| Uploads bucket | `gs://lnic-source-directory-uploads` — private, versioned |
| Registry | `us-central1-docker.pkg.dev/lnic-source-directory/app` |
| Runtime SA | `directory-run@` — Cloud SQL client, secret accessor, bucket writer |
| Deploy SA | `github-deploy@` — Run developer, registry writer, SA user |
| Secrets | `django-secret-key`, `db-password` |
| Database | `directory` on `mizzou-news-crawler:us-central1:mizzou-db-prod` |
| Admin hostname | `sources.localnewsimpact.org` via Cloud Run domain mapping |

Not yet created: the Cloud Run service, its domain mapping, IAP.

## Reuse instead of duplication

Two things are borrowed from `mizzou-news-crawler` rather than bought again:

**The database instance.** `mizzou-db-prod` (POSTGRES_16, `db-g1-small`) already
runs in us-central1. This project has its own `directory` database and
`directory` user on it, and `directory-run@` holds `roles/cloudsql.client` on the
crawler project — the only permission this project has there, and one that grants
connection and nothing else. A dedicated instance would have been ~$50/month to
hold 2,000 rows.

Isolation is therefore database-and-user level rather than instance level. Worth
being clear-eyed about the one gap that leaves, below.

**No load balancer.** A Cloud Run domain mapping puts the admin on
`sources.localnewsimpact.org` for free. The load balancer path is ~$18/month
and is kept in the script only as a fallback.

Together: **~$70/month becomes ~$2–5/month.**

### Open: PUBLIC has CONNECT

Postgres grants `CONNECT` on a database to `PUBLIC` by default, so the new
`directory` role can most likely open the crawler's `mizzou` database as well.
Not verified on this instance — checking it needs a SQL session, not the admin
API. Close it before the directory holds real data:

```sql
REVOKE CONNECT ON DATABASE mizzou FROM PUBLIC;
GRANT  CONNECT ON DATABASE mizzou TO mizzou_user;
```

That changes the crawler's instance, not just this database, so it should be run
with the crawler owners rather than unilaterally.

### Admin hostname

Cloud Run domain mappings are supported in us-central1. The route is:

```
sources.localnewsimpact.org  ->  A/CNAME in Route 53  ->  Cloud Run
```

`gcloud run domain-mappings create` prints the exact records once the service
exists. Two things to settle at that point:

1. The domain must be verified in Search Console before a mapping is accepted.
2. Whether IAP covers a domain-mapped hostname. If it does not, the fallback is
   Google OAuth inside Django restricted to the `localnewsimpact.org` hosted
   domain — no load balancer, no extra cost, and arguably simpler than IAP.

### GitHub Actions

```yaml
workload_identity_provider: projects/666766099662/locations/global/workloadIdentityPools/github/providers/github
service_account: github-deploy@lnic-source-directory.iam.gserviceaccount.com
```

The provider is bound to `LocalNewsImpact/NewsSourceDirectory` by an attribute
condition, so no other repository can assume it.

### DNS

Route 53 holds `localnewsimpact.org`, with a `*` A record on the WordPress host
(50.16.132.48). A record for an exact name beats the wildcard, so no wildcard
change is needed for either the admin hostname or the feed.

## Public ingress

Cloud Run rejects a request with 403 before it reaches Django unless something
holds `roles/run.invoker`. `--allow-unauthenticated` grants that to `allUsers`,
which the organisation's Domain Restricted Sharing policy refuses — the same
constraint that blocked the public bucket.

**gcloud reports this as a warning and exits zero.** The first real deploy built
the image, ran migrations and served a revision while leaving it unreachable:

```
Setting IAM Policy............warning
Completed with warnings:
  Setting IAM policy failed, try "gcloud ... --role=roles/run.invoker"
```

`deploy.yml` now checks for the binding after deploying and fails when it is
absent, so that cannot pass silently again.

The project therefore carries an exception, set on this project alone while the
rest of the organisation keeps its restriction:

```bash
# exception.yaml
#   constraint: constraints/iam.allowedPolicyMemberDomains
#   listPolicy: {allValues: ALLOW}
gcloud resource-manager org-policies set-policy exception.yaml \
  --project=lnic-source-directory
```

It was needed rather than preferred. The researcher portal must admit accounts
outside the domain, and those can never be IAM principals while the constraint
applies, so public ingress was required eventually regardless — taking it here
keeps one authentication system instead of two.

The cost is worth stating plainly: **this project no longer restricts external
IAM principals**, so someone could grant an outside account access to it. The
database is protected separately (see Database isolation), but the project
boundary is now a thing being trusted rather than enforced.

## How the service reaches the database

Cloud Run connects to Cloud SQL through a **unix socket** at
`/cloudsql/<connection name>`, not a host and port. The deploy therefore passes
`CLOUD_SQL_CONNECTION_NAME` and the service assembles its own DSN in
`config/db.py`.

Passing a `DATABASE_URL` instead does not fail loudly — it points the deployed
service at its own localhost, and the first real deploy did exactly that:

```
Is the server running on that host and accepting TCP/IP connections?
```

Two consequences worth keeping:

- The password reaches the container as `DB_PASSWORD` from Secret Manager and is
  never assembled into a URL, so it does not appear in a deploy command or a
  revision's environment as part of a longer string.
- `gcloud run deploy --set-env-vars` **replaces** the whole environment. Two of
  those flags on one command silently discards the first, so there is exactly one
  per command in `deploy.yml`.

## Database isolation

The directory shares the crawler's instance but must not be able to reach its
database. Two defaults stood in the way, and both are now closed by
`infra/sql/isolate_directory_role.sql`:

1. **Postgres grants `CONNECT` on every database to `PUBLIC`.** The `directory`
   role could open `mizzou`. Verified by connecting, not assumed.
2. **Cloud SQL adds every API-created user to `cloudsqlsuperuser`.** This was the
   larger hole. Membership confers rights across the instance, so revoking
   `CONNECT` alone would have been theatre — a member can `SET ROLE` and undo it.

State after applying:

```
mizzou     =T/cloudsqlsuperuser            PUBLIC: TEMP only, no CONNECT
           mizzou_user=c, datastream_user=c
directory  =T/directory                    PUBLIC: TEMP only, no CONNECT
           directory=CTc                   owns its own database
```

`directory` holds no role memberships at all. Verified in both directions:

| From | To | Result |
|---|---|---|
| `directory` | `mizzou` | `FATAL: permission denied for database "mizzou"` |
| `directory` | `directory` | connects, owns it, migrations can create tables |
| `mizzou_user` | `mizzou` | unaffected — 48 tables, 1,149 source rows |

The directory role owns its own database, which is what lets it lose superuser
rights without losing the ability to migrate.

To rerun:

```bash
./infra/sql/apply.sh infra/sql/isolate_directory_role.sql
```

The script is in two halves because ownership moves partway through: after that,
the crawler's role can no longer alter the directory database, and attempting it
produces a *warning* rather than an error — which is easy to miss. `apply.sh`
runs the second half as the `directory` role.

## The read-only role

`directory_ro` exists so the QA publish workflow can read the registry from a
GitHub runner without being able to change it. A mistake in a workflow file
cannot alter curated data — Postgres refuses, rather than our care being the
thing that prevents it.

```
read  the registry   outlets: 2809, places: 231389
write the registry   permission denied for table directory_outlet
reach mizzou         permission denied for database "mizzou"
```

Its password is the `DB_RO_PASSWORD` repository secret. Created by
`infra/sql/create_readonly_role.sql` and `grant_readonly.sql`, in that order and
over two connections: role creation is cluster-wide and needs a
cloudsqlsuperuser, while the grants must be made by `directory`, which owns the
database.

`ALTER DEFAULT PRIVILEGES` matters as much as the grants. Without it a table
added by a future migration would be invisible to the publisher, and the feed
would quietly lose a column instead of failing.

## Open decision: the feed bucket cannot be public

The org enforces `constraints/iam.allowedPolicyMemberDomains`, restricted to
customer `C04iy3g4y`. Two consequences discovered while bootstrapping:

1. An IAM **condition** cannot be attached to a public binding
   (`Conditions are not allowed on public resources`), so a `feed/` prefix
   cannot be a security boundary. Hence two buckets rather than one — everything
   in the feed bucket is public by construction, and the uploads bucket is
   separate and private.
2. `allUsers` is refused outright: *One or more users named in the policy do not
   belong to a permitted customer.* **No bucket in this org can be made public
   as things stand.**

The options, in the order worth trying:

**A. Project-scoped exception.** Add a policy on `lnic-source-directory` only,
permitting public members alongside the customer. The rest of the org keeps its
current posture. The cost is that this one project no longer restricts external
identities generally — someone could grant an outside account access to the
database here — so it trades a broad guarantee for a narrow one.

**B. Serve the feed from the WordPress host.** `publish` pushes the feed to the
AWS host instead of GCS. No org policy change, no load balancer, no CORS at all
since the widget would then be same-origin. The cost is a cross-cloud publish
step and the feed's availability being tied to the WordPress host.

**C. A small public Cloud Run service** reading the private bucket. No policy
change, negligible cost at this traffic, but it puts a service back in the read
path. It would still never touch Postgres.

Until one is chosen the bucket exists and is writable by the runtime; only the
public grant is missing, and `bootstrap.sh` reports it rather than failing.
