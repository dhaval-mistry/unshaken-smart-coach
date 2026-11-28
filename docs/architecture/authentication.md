# Authentication: Google first

Status: **owner-approved Google-only initial release**. Apple and account linking
are deferred. FastAPI handles provider sign-in; private APIs use application
sessions and resolve ownership from PostgreSQL. Keep identity keyed by verified
provider, issuer and subject so later providers can reuse this boundary.
Never link accounts by email. Existing identities and workout history are preserved.

## How login works

Use direct provider sign-in handled by FastAPI and a PostgreSQL-backed session.
The browser never stores provider tokens in local storage.

1. The browser starts Google login through FastAPI.
2. FastAPI creates a five-minute, single-use login transaction tied to a random
   browser-binding cookie. It stores the provider, purpose, random `state` and
   `nonce`, and an allowed return location. Never accept an arbitrary redirect.
3. The provider signs the person in and returns a temporary authorization code.
   FastAPI checks the browser binding and `state`, consumes the transaction
   atomically, then exchanges the code server-side using the exact registered
   callback. Use Google PKCE where supported by the selected library.
4. A maintained validation library checks the ID token's signature, allowed
   algorithm, configured issuer, client audience, expiry and matching `nonce`.
   Keys come only from fixed provider endpoints, with bounded HTTPS requests
   and key-cache refresh. An access token is not a substitute for an ID token.
5. Resolve the verified `(provider, issuer, subject)` to the application user.
   An active existing user receives a fresh application session. New users first
   confirm a display name and explicitly choose kg or lb; the short-lived
   onboarding transaction gives no workout access. Create user, identity and
   session together after validation. Never invent the required unit default.

Google uses a GET callback. Reject replayed or mismatched responses.

## Application session and access

Use one same-origin HTTPS browser entry point for UI and `/api` forwarding
to FastAPI. Local authenticated browser testing needs a separate HTTPS setup;
the existing loopback Docker service remains unchanged until implementation.

- Use an opaque 256-bit random session token in a `__Host-unshaken_session`
  cookie: `Secure; HttpOnly; SameSite=Lax; Path=/`, with no `Domain` attribute.
  Store only its hash in PostgreSQL, linked to the user and login identity.
- Session lifetime: eight hours absolute and 30 minutes idle, checked server-side.
  No persistent "remember me" or silent application-session extension beyond
  eight hours. A new login rotates the token. Multiple browser sessions are allowed.
- Every private request checks the session, expiry/revocation and active user.
  Database unavailability fails closed with a safe `503`, not anonymous access.
  A shared `current_user` dependency supplies the user to services. All queries
  and child-resource changes enforce that owner in the database transaction.
- Missing/expired credentials use `401 authentication_required`; unknown and
  another user's private IDs share `404 not_found`. Invalid cross-site requests
  use safe `403 forbidden`. Public health and lookup routes stay public.
- Browser mutations, onboarding and logout require an exact allowed
  `Origin` plus a session/transaction-bound CSRF token in a custom header. Return
  that token through a no-store JSON response; keep it in browser memory.
  CORS and SameSite alone are insufficient. Login callbacks use their dedicated
  single-use transaction checks instead.
- Logout revokes the current session in PostgreSQL and clears its cookie; it
  does not sign the person out of Google. Do not report successful server
  revocation if the database write failed. A disabled user invalidates all sessions.

This cookie/hash approach follows [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
Session IDs authenticate requests; request IDs and trace IDs only help debugging.

## Future providers

Apple sign-in, provider-specific credentials and notifications, and account linking
need a separate delivery phase and verification. Google login requests no offline
access or refresh token. Existing sessions use the approved expiry and revocation
policy; provider account changes are not detected immediately.

PR #50 retains the existing Apple implementation for future use. Treat Apple
and account linking as disabled throughout the initial release. Apple start
and callback requests, Apple notifications, and account linking must not
create or mutate auth state, exchange codes, or contact Apple. The private
session boundary accepts only Google identities for this release, including
when the database contains Apple identities or sessions. Enabling the retained
paths requires a separate approved delivery with provider configuration and
live verification.

## Endpoints and storage

| Boundary | Responsibility |
|---|---|
| `/api/v1/auth/{provider}/start` and `/callback` | Google-only allowlist; login transaction and code exchange; callbacks never return tokens in redirects |
| `GET /api/v1/auth/session` | Current user's minimal profile and CSRF token; never raw session/provider tokens |
| `POST /api/v1/auth/onboarding` | Complete the verified first-login transaction with name and unit |
| `POST /api/v1/auth/logout` | Revoke current application session |

Limit input sizes, login attempts and pending transactions; callbacks return
to a fixed UI completion/error page.
Use shared safe errors, no-store headers and finite provider timeouts. Provider
failure returns safe `503 authentication_unavailable`; failed proof returns
safe `401 authentication_failed` without raw provider details.

Migration `0004_auth_storage` provides the shared database foundation. Preserve
`0001`–`0004` and all existing identities and historical data. Retain PR #50's
`0005_apple_onboarding` migration, including its Apple storage and its shared
attempt limits and bounded transaction retention. The presence of Apple storage
does not enable Apple sign-in.
Reject unavailable providers before creating transactions or making network calls.
Apple settings and encryption keys are optional and cannot enable Apple or
linking in the initial release. Google-only startup and session flows work
with those settings absent.

Keep handlers in `app/api`, shared verification/current-user logic in a small
`app/auth` package, and persistence in `app/db`. Extend the Docker source
allowlist deliberately for the new package. Never put callbacks, codes, tokens,
cookies, email, user IDs or raw provider exceptions in logs/traces or metric
labels. Record only bounded provider/action/outcome categories and safe request
correlation. Suppress callback query/body logging, including proxy/server logs.

## Local setup and verification

Use [the local backend setup](../setup/backend.md#local-browser-authentication)
with Caddy on loopback and one origin, `https://localhost:8443`. Google returns to
`https://localhost:8443/api/v1/auth/google/callback`. Keep UI and API on the same
origin. Keep credentials in a private runtime file outside the source tree.

Use signed Google fixtures and disposable PostgreSQL 17 for proof validation,
replay, concurrent onboarding, expiry, logout, CSRF, ownership, failure handling,
attempt limits, cleanup and safe telemetry. The current supported development
environment is Windows with Docker Desktop using Linux containers. The full
backend suite also passed in Linux containers under Docker Desktop; that is not
native Linux-host verification. Native Linux host/browser verification is
deferred. Owner-reported live Google browser evidence, signed fixtures and
synthetic proxy checks are distinct and must be reported separately. #47 owns
local setup, and #48 owns the Google implementation and its browser verification.
Private workout APIs depend on the merged Google authentication boundary and
their own approved scope.

Verify that Google starts and completes sign-in with only the placeholder
configuration fields supplied privately. Also verify that providing Apple
configuration does not enable the deferred paths, unsupported requests have no
database or provider side effects, and sessions tied to Apple identities cannot
authorize private requests. Run the migration and schema checks on disposable
PostgreSQL 17 with the retained Apple storage in place.
