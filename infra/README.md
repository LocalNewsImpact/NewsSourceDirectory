# Infrastructure

`bootstrap.sh` is the description of the project. Every stage checks before it
creates, so rerunning is safe and reading it tells you what exists.

```bash
./infra/bootstrap.sh                  # everything, including the database
./infra/bootstrap.sh sql              # just the database and its grant
./infra/bootstrap.sh lb_ip lb         # fallback only — see "Admin hostname"
```

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
| Admin hostname | `directory.localnewsimpact.org` via Cloud Run domain mapping |

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
`directory.localnewsimpact.org` for free. The load balancer path is ~$18/month
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
directory.localnewsimpact.org  ->  A/CNAME in Route 53  ->  Cloud Run
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
