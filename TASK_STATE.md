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
