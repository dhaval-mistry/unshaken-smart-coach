# Task state

## Latest completed milestone

- Implemented issue #46 on feature/46-auth-storage. Revision 0004 adds
  authentication sessions, single-use transactions, and bounded Apple
  credential ciphertext and key-version storage.
- Existing migrations 0001–0003 remain frozen. The upgrade does not rewrite
  legacy identities or workout data.
- Verification uses the repository's disposable PostgreSQL 17 runner.
- PR #49 review follow-up checks transaction expiry at consumption time and
  covers already expired transactions separately from concurrent consumption.

## Next handoff

- Review the #46 pull request before any merge or database rollout.
- Issue #48 owns FastAPI authentication and encryption before persistence.
- Issue #47 is the owner-managed provider and local HTTPS setup.

## Issue #48 in progress

- PR #49 merged into main at 54f02ae and closed #46.
- Feature branch: feature/48-provider-authentication.
- Added the Apple credential encryption primitive and verified its round trip
  and failure handling with synthetic keys. Persistence and the FastAPI
  authentication flows are still pending.
- Real provider browser verification depends on the owner-managed #47 setup.

## Issue #48 implementation milestone

- Added the approved revision 0005, pending Apple encryption, promotion,
  revocation state and bounded cleanup.
- Wired local FastAPI sign-in, session, onboarding, logout, linking and
  notification routes using private runtime settings.
- Signed synthetic Google and Apple fixtures exercise local provider exchanges
  on the disposable PostgreSQL 17 runner. Live browser and provider setup
  remains tracked in #47.

## PR #50 review follow-up

- Signed Apple revocation serializes with pending onboarding and identity writes,
  clears pending credentials and invalidates affected established sessions.
- Login and linking admission enforce short per-source windows. Startup and
  periodic cleanup remove stale rows in bounded batches, with a small additional
  batch during transaction admission.

## Google-only rollout

- PR #50 serves Google sign-in and rejects Apple and linking routes before
  touching auth state or contacting a provider. The active session and
  onboarding boundaries accept only Google.
- The private runtime JSON needs only the origin, Google client ID and Google
  client secret. PR #50 retains Apple code, credential storage, migration 0005,
  source admission and bounded transaction cleanup for the approved rollout.
- Live Google browser verification remains dependent on local setup in #47.

## PR #50 Google rollout review follow-up

- Same-browser session replacement revokes the previous token and issues the
  successor atomically. Sessions in other browsers remain available.
- Expected Google callback failures return to the fixed same-origin
  `/auth/error` page without a query string or provider details.

## Local HTTPS handoff

- `compose.auth.yaml` opts into a loopback Caddy origin on port 8443. It mounts
  the private runtime file only into FastAPI and serves a small static Google
  sign-in verification page.
- The setup guide records Windows and Linux certificate trust steps. Owner
  trust and live Google sign-in remain manual. Use disposable PostgreSQL for
  first verification and leave the existing database and observability stack
  in place.

## PR #50 Tester coverage follow-up

- Added disposable API checks for two-user session and logout isolation,
  idle and absolute expiry, disabled users and concurrent first onboarding.
- The signed Google flow exercises login and logout with a failing telemetry
  span exporter, and checks that both operations attempted export.
- The optional Caddy verifier provisions only its own synthetic PostgreSQL
  database and checks the throttled HTTP response through local HTTPS.

## PR #50 verifier review follow-up

- Verify the published HTTPS source against a measured Docker TCP peer and
  check that caller forwarding input does not change the limit window.
- The disposable verifier reports its project and exits nonzero if cleanup
  fails. It never prints raw Compose output or verification cookie data.
