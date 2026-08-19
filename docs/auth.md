# Authentication and the two front ends

Two audiences with different trust levels, one codebase.

| | `sources.localnewsimpact.org` | `research.localnewsimpact.org` |
|---|---|---|
| Audience | staff editors | outside researchers |
| Routes | admin only | portal only |
| Accounts | `@localnewsimpact.org` only | any Google account, approval-gated |
| Database role | `directory` — read/write | `directory_ro` — SELECT only |
| Exists | planned, M2 | later |

## One image, two services

The same container runs both, with a different `ROOT_URLCONF` per service. The
admin URLs are not merely permission-denied on the portal — they are not routed
at all, so a permissions bug cannot expose them.

Two Cloud Run services that both scale to zero cost the same as one, so the
isolation is free.

The stronger half of the split is the database role. The portal connects as
`directory_ro`, which holds `SELECT` and nothing else. Researchers cannot write
regardless of what the application does, and that is enforced by Postgres rather
than by our code.

## Why not IAP

IAP would stop unauthenticated requests at Google's edge, before they reach
Django, which is genuinely stronger than an in-app check. It was the original
plan. Three things moved the decision:

1. The portal must admit accounts outside the organisation, and an IAP grant is
   an IAM binding — which the org's Domain Restricted Sharing policy refuses. The
   portal therefore needs application-level auth no matter what.
2. Given that, IAP on the admin means maintaining two auth systems for two front
   ends of one application.
3. Whether IAP covers a Cloud Run domain-mapped hostname is unverified, and the
   fallback if it does not is the very thing we would otherwise be building.

Local development also becomes identical to production, which it never is with
IAP in front.

The trade is accepted deliberately: unauthenticated requests reach Django. For an
admin used by fewer than ten people behind a verified domain claim, that is a
reasonable exchange for one auth system instead of two.

## The domain restriction must be enforced server-side

```python
SOCIALACCOUNT_PROVIDERS = {"google": {"AUTH_PARAMS": {"hd": "localnewsimpact.org"}}}
```

**`hd` is a hint to Google's account chooser, not enforcement.** It changes which
accounts are offered. It does not prevent anyone completing the flow with a
personal account.

The claim has to be checked server-side, in an allauth adapter:

```python
class AdminSocialAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        extra = sociallogin.account.extra_data
        if extra.get("hd") != "localnewsimpact.org" or not extra.get("email_verified"):
            raise ImmediateHttpResponse(render(request, "account/not_allowed.html", status=403))
```

Both halves matter: `hd` establishes the domain, `email_verified` stops an
unverified address claiming one. Without this the login screen looks restricted
and is not.

The portal service uses a different adapter that deliberately does not check
`hd`, and instead requires an approved access request.

## Portal access requests

Researchers sign in, request access, and a staff member approves in the admin.
That flow is also the natural place for terms acceptance and a record of who
downloaded what, if either is ever needed.

Nothing about it is designed yet, and nothing in the current schema forecloses
it — `Outlet` and `CoverageRecord` do not care who reads them.
