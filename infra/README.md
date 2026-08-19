# Infrastructure

`bootstrap.sh` is the description of the project. Every stage checks before it
creates, so rerunning is safe and reading it tells you what exists.

```bash
./infra/bootstrap.sh                  # everything except the database
./infra/bootstrap.sh sql              # ~$50/month — run deliberately
./infra/bootstrap.sh lb               # after the first Cloud Run deploy
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
| Admin address | `34.36.165.214`, reserved for `directory.localnewsimpact.org` |

Not yet created: Cloud SQL, the load balancer, IAP.

### GitHub Actions

```yaml
workload_identity_provider: projects/666766099662/locations/global/workloadIdentityPools/github/providers/github
service_account: github-deploy@lnic-source-directory.iam.gserviceaccount.com
```

The provider is bound to `LocalNewsImpact/NewsSourceDirectory` by an attribute
condition, so no other repository can assume it.

### DNS

Route 53 holds `localnewsimpact.org`, with a `*` A record pointing at the
WordPress host. Create this record — an exact name beats the wildcard:

```
directory.localnewsimpact.org.   A   34.36.165.214
```

Create it **before** running `./infra/bootstrap.sh lb`: a Google-managed
certificate will not issue until the hostname already resolves to the address.

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
