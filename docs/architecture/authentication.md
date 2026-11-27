# Google and Apple sign-in

Status: **owner-approved design; authentication is not implemented**. On
2026-11-26 the owner selected Google and Apple, replacing Microsoft, then approved
all recommendations in this document in the Solution Architect follow-up:
direct FastAPI login, cookie sessions and lifetimes, explicit onboarding and
verified account linking. Reviewed against main `1c659bd`. This is the design
for the authentication prerequisite for
[issues #21–#29](../api/README.md#issue-to-design-coverage), not permission to
implement their other unresolved rules.

## How login works

Use direct provider sign-in handled by FastAPI and a PostgreSQL-backed session.
The browser never stores provider tokens in local storage.

1. The browser starts Google or Apple login through FastAPI.
2. FastAPI creates a five-minute, single-use login transaction tied to a random
   browser-binding cookie. It stores the provider, purpose, random `state` and
   `nonce`, and an allowed return location. Never accept an arbitrary redirect.
3. The provider signs the person in and returns a temporary authorization code.
   FastAPI checks the browser binding and `state`, consumes the transaction
   atomically, then exchanges the code server-side using the exact registered
   callback. Use Google PKCE where supported by the selected library; do not
   assume Apple's documented flow supports the same parameters.
4. A maintained validation library checks the ID token's signature, allowed
   algorithm, configured issuer, client audience, expiry and matching `nonce`.
   Keys come only from fixed provider endpoints, with bounded HTTPS requests
   and key-cache refresh. An access token is not a substitute for an ID token.
5. Resolve the verified `(provider, issuer, subject)` to the application user.
   An active existing user receives a fresh application session. New users first
   confirm a display name and explicitly choose kg or lb; the short-lived
   onboarding transaction gives no workout access. Create user, identity and
   session together after validation. Never invent the required unit default.

Apple uses an HTTPS form-POST callback when requesting name/email. The temporary
browser-binding cookie therefore needs `Secure; HttpOnly; SameSite=None` and
must be cleared after callback/expiry. Validate both binding and `state` even
on error responses; this narrow callback does not bypass protection on other
routes. Google uses a GET callback. Reject replayed or mismatched responses.
These provider details follow [Google's server flow](https://developers.google.com/identity/openid-connect/openid-connect)
and [Apple's authorization contract](https://developer.apple.com/documentation/signinwithapplerestapi/request-an-authorization-to-the-sign-in-with-apple-server.).

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
- Browser mutations, onboarding, linking and logout require an exact allowed
  `Origin` plus a session/transaction-bound CSRF token in a custom header. Return
  that token through a no-store JSON response; keep it in browser memory.
  CORS and SameSite alone are insufficient. Login callbacks use their dedicated
  single-use transaction checks instead.
- Logout revokes the current session in PostgreSQL and clears its cookie; it
  does not sign the person out of Google/Apple. Do not report successful server
  revocation if the database write failed. A disabled user invalidates all sessions.

This cookie/hash approach follows [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
Session IDs authenticate requests; request IDs and trace IDs only help debugging.

## Account linking and provider revocation

Never join accounts by email, even when both providers mark it verified. Apple
may supply a private relay address and supplies its name object only on first
authorization; treat profile names as optional input, not proof of identity.

To add a second provider, require an existing session, a fresh verification of
the current login identity within five minutes, and a separate provider flow
bound to that user and the `link` purpose. Atomically attach only an identity
that is not already owned by another user. A conflict does not merge users or
move workouts. Rotate/revoke the user's existing sessions after a successful
link and issue a fresh one. Unlinking, account merging, recovery and account
erasure need separate approved behavior; do not implement them implicitly.

Apple refresh credentials needed for provider revocation are encrypted with a
versioned key outside the database/image. Follow [Apple's token lifecycle](https://developer.apple.com/documentation/technotes/tn3194-handling-account-deletions-and-revoking-tokens-for-sign-in-with-apple)
and [signed notification guidance](https://developer.apple.com/documentation/signinwithapple/processing-changes-for-sign-in-with-apple-accounts):
validate notifications before invalidating affected login sessions. Provider
revocation or a definitively invalid Apple refresh check revokes affected sessions
and blocks new ones through that identity; it does not erase retained workouts.
Transport failures are not proof of revoked consent. No Google offline API scope
or refresh token is needed just for login. Immediate detection of every external
Google account change is not promised by the initial eight-hour session policy.

## Endpoints and storage

| Boundary | Responsibility |
|---|---|
| `/api/v1/auth/{provider}/start` and `/callback` | Google/Apple allowlist; login transaction and code exchange; callbacks never return tokens in redirects |
| `GET /api/v1/auth/session` | Current user's minimal profile and CSRF token; never raw session/provider tokens |
| `POST /api/v1/auth/onboarding` | Complete the verified first-login transaction with name and unit |
| `POST /api/v1/auth/logout` | Revoke current application session |
| `POST /api/v1/auth/identities/{provider}/link` | Start the protected linking flow; callback uses stored purpose/user |
| `POST /api/v1/auth/apple/notifications` | Verify signed provider events and revoke affected sessions |

Limit input sizes, login attempts and pending transactions; callbacks return
to a fixed UI completion/error page.
Use shared safe errors, no-store headers and finite provider timeouts. Provider
failure returns safe `503 authentication_unavailable`; failed proof returns
safe `401 authentication_failed` without raw provider details.

One reviewed successor migration must permit `apple` identities and add the
session, temporary login/onboarding transaction and encrypted Apple credential
storage above. Existing code permits only `google`/`microsoft`; documentation
alone does not change that constraint. Reject future Microsoft sign-in without
deleting existing identity rows or history. Inspect legacy rows during migration
planning; existing Microsoft-only account transition requires owner direction.
Freeze migrations 0001–0003. No separate auth tables per workout API.

Keep handlers in `app/api`, shared verification/current-user logic in a small
`app/auth` package, and persistence in `app/db`. Extend the Docker source
allowlist deliberately for the new package. Never put callbacks, codes, tokens,
cookies, email, user IDs or raw provider exceptions in logs/traces or metric
labels. Record only bounded provider/action/outcome categories and safe request
correlation. Suppress callback query/body logging, including proxy/server logs.

## Local setup and verification

The owner supplies provider accounts and registers exact callbacks. Required
private settings include Google client ID/secret, Apple Services ID/Team ID/key
ID/private key, session origin, callback URLs and credential-encryption key.
Only public identifiers may reach the UI. Keys stay outside source/build context;
pass required server secrets at runtime using reviewed secret-file configuration.

- **Google:** register a Web application client, consent/test users and exact
  redirect URI. [Google permits localhost callbacks](https://developers.google.com/identity/protocols/oauth2/web-server),
  but the shared secure-cookie test path should use local HTTPS.
- **Apple:** needs an enabled primary App ID, associated Services ID, signing key
  and registered web domain/HTTPS return URL. Apple rejects localhost/IP return
  URLs. A developer-owned HTTPS domain routed to the local app through a reviewed
  TLS proxy/tunnel is required for real browser tests; do not expose PostgreSQL
  or Grafana. Provider setup/account access is an external prerequisite, not an
  instruction to purchase or deploy anything. See [Apple's web setup](https://developer.apple.com/help/account/capabilities/configure-sign-in-with-apple-for-the-web).

Automated tests use signed fixtures and disposable PostgreSQL 17: invalid proofs,
state/nonce/replay, expiry/logout, CSRF, concurrent linking, two-user isolation,
disabled accounts, safe telemetry and provider/database outages. Browser checks
verify both providers, secure cookies, first-login onboarding and logout. Report
fixture tests separately from real provider tests; never weaken checks for local
development or substitute a caller-provided user ID.

## Approval and handoff

The approved session, onboarding and linking decisions close D8's design gate
for this scope. Authentication still needs implementation, review and testing.
Provider configuration and the local HTTPS entry point are setup prerequisites;
no provider account, purchase, deployment or database change is authorized here.
Unlinking, recovery, merging, erasure and any existing Microsoft-only account
transition remain outside the approved behavior above.

Product Owner prepares the auth/migration implementation story
and updates the Google/Microsoft wording and dependencies in #21–#29. Those
issues still retain their independent D3–D7/D9 gates. Developer and Tester are
requested separately. This design changes no code, schema, provider account,
existing database, Docker service or deployment configuration.
