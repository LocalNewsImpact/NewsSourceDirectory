# Runbook

What to do when something is broken or someone needs access. Facts here were
checked against the live projects on 2026-08-19; the procedures marked
**unexercised** have not been performed, so treat the first run as the rehearsal.

| | |
|---|---|
| Admin | `sources-admin`, Cloud Run, `us-central1`, project `lnic-source-directory` |
| Image | Datadesk's, run with `SERVICE_ROLE=sources` — this repository ships as a package inside it |
| Database | schema `directory` in `datadesk`, on `mizzou-news-crawler:us-central1:mizzou-db-prod` |
| Feed | the `gh-pages` branch of this repository |

---

## The admin is broken after a deploy

The deploy came from Datadesk — sources-admin runs its image — so the fix
forward belongs there. The roll back belongs here: Cloud Run keeps every
revision, and reverting is a traffic change, not a rebuild, taking seconds.

```bash
gcloud run revisions list --service=sources-admin \
  --region=us-central1 --project=lnic-source-directory --limit=5

gcloud run services update-traffic sources-admin \
  --region=us-central1 --project=lnic-source-directory \
  --to-revisions=sources-admin-00017-jcs=100
```

Return to normal once the fix is deployed:

```bash
gcloud run services update-traffic sources-admin \
  --region=us-central1 --project=lnic-source-directory --to-latest
```

**Migrations do not roll back with the traffic.** They run in a Cloud Run job
before traffic shifts, so by the time a revision is serving, the schema has
already changed. Rolling back to a revision that predates a migration puts old
code in front of a new schema. If the bad deploy included a migration, roll the
traffic back to stop the bleeding and then fix forward — do not assume the
previous revision is safe.

Check which revision is serving:

```bash
gcloud run services describe sources-admin --region=us-central1 \
  --project=lnic-source-directory --format='value(status.traffic)'
```

## A change here did not reach the site

Merging to `main` here ships nothing and migrates nothing. sources-admin runs
Datadesk's image with `SERVICE_ROLE=sources`, and the `directory` package inside
that image is pinned to a version tag in Datadesk's `requirements.txt`:

```
news-source-directory @ git+https://github.com/LocalNewsImpact/NewsSourceDirectory@v0.1.0
```

So a change here reaches the site in three steps: tag a release in this
repository, bump that pin in Datadesk, and let Datadesk's deploy build and roll
out the image. Comparing the pinned tag against `git describe --tags` here tells
you how far the serving code is behind this branch.

---

## The feed published something wrong

The public directory reads static files from `gh-pages`. The database is not
involved, so nothing a reader sees changes until a publish runs.

**There is no previous version to revert to.** The publish workflow builds an
orphan branch and force-pushes it, so `gh-pages` carries exactly one commit. `git
revert` has nothing to work with.

Two ways back, in order of preference:

**Fix the data and republish.** Correct the records in the admin, then use
**Publish the public feed now** from the outlet list. This is right whenever the
data was wrong, which is the usual case.

**Repoint the manifest.** The feed is content-addressed: `manifest.json` names
hashed payload files, and the older payloads from previous publishes are usually
still on the branch. If a publish shipped a bad payload but a good one is still
there, editing `manifest.json` to name the older file restores the previous
directory without a rebuild. Verify the file is present before relying on this —
it is a consequence of how the branch is written, not a guarantee.

To take the directory down entirely, revoke nothing and publish nothing: remove
the shortcode from the WordPress page. That is faster than anything involving
GitHub and does not touch the registry.

---

## Database backup and restore

**Backups exist.** Verified on the instance: daily automated backups at 07:00
UTC, 7 retained, point-in-time recovery enabled with 7 days of transaction logs.
The three most recent automated backups were successful.

```bash
gcloud sql backups list --instance=mizzou-db-prod --project=mizzou-news-crawler
```

**The trap: restore is instance-level, not database-level.** `mizzou-db-prod`
carries both the crawler's `mizzou` database and this project's `directory`
database. Restoring a backup onto that instance rolls the crawler back as well,
to a point it did not ask for. **Never restore in place.**

The safe path is to recover a copy and move only what is needed
(**unexercised**):

1. Restore the backup, or a point in time, to a **new instance**. Point-in-time
   recovery creates a new instance by design; a backup restore must be told to.
2. Connect to the new instance and `pg_dump` only the `directory` database.
3. Restore that dump into the live `directory` database, or into a renamed one
   alongside it if the failure is not yet understood.
4. Delete the recovery instance. It costs money for as long as it runs.

Because the recovery path crosses two projects and involves another team's data,
agree it with the crawler owners before starting, not during.

**A logical backup is cheaper insurance than a restore.** Before any bulk import
or a destructive management command, take a dump of just this database:

```bash
pg_dump "$DATABASE_URL" --no-owner --format=custom > directory-$(date +%F).dump
```

Reaching the database from a laptop needs the Cloud SQL proxy; no IAM database
users exist on this instance, so `--auto-iam-authn` alone will not authenticate
and the `directory` password from Secret Manager is required.

---

## Running a command against production

```bash
./infra/manage.sh rebuild_outlets
./infra/manage.sh seed_places --url --link
```

It runs inside Cloud Run using the image the service is currently serving, so the
code is exactly what production runs and nothing is installed locally. Your
machine never connects to the database.

`rebuild_outlets` is the one to be careful with: it fills blank fields and
refreshes counts, but `--force` overwrites curated values and destroys review
work. There is no undo.

---

## Access

**Granting admin access.** The person needs a `@localnewsimpact.org` Google
identity — Domain Restricted Sharing refuses anything else, and a personal Gmail
address cannot be granted a role in this organisation.

```bash
./infra/manage.sh ensure_admin someone@localnewsimpact.org
```

Matching is by email, so this promotes an existing account rather than creating a
second one for the same person. Creating one by hand through the admin instead
produces a duplicate account that logs in but has none of the right permissions.

**Removing access.** Clear the account's staff and superuser flags in the admin.
Deleting the user is worse: audit history references it.

**Sign-in is checked server-side.** The Google `hd` parameter is a hint, not
enforcement; the adapter verifies the hosted domain and the verified-email claim
on every login. See [auth.md](auth.md).

---

## Escalation

| Symptom | Look at |
|---|---|
| Admin returns 403 before Django is reached | The public invoker binding was refused — `infra/README.md`, "Public ingress" |
| Admin returns 503 from `/_health` | The database is unreachable; the health check does a real query |
| Deploy is green but the site is unchanged | The push event did not fire — above |
| Publish succeeded but the page is stale | `manifest.json` is short-TTL and payloads are immutable; check the manifest actually changed |
