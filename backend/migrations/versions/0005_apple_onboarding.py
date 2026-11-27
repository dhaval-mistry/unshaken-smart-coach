"""Add temporary Apple credential storage for first-login onboarding."""

import os

from alembic import op

revision = "0005_apple_onboarding"
down_revision = "0004_auth_storage"
branch_labels = None
depends_on = None


def upgrade():
    """Add bounded pending envelopes and a durable identity revocation marker."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SELECT pg_catalog.pg_advisory_xact_lock(746231901)")
    op.execute("""
        ALTER TABLE public.user_identities ADD COLUMN provider_revoked_at timestamptz;
        ALTER TABLE public.user_identities ADD CONSTRAINT ck_auth_provider_revoked
          CHECK (provider_revoked_at IS NULL OR (provider = 'apple' AND isfinite(provider_revoked_at)));
        ALTER TABLE public.auth_transactions ADD COLUMN link_session_hash bytea CHECK (
            link_session_hash IS NULL OR (purpose = 'link' AND octet_length(link_session_hash) = 32)
        );
        CREATE TABLE public.apple_revoked_proofs (
          proof_hash bytea PRIMARY KEY CHECK (octet_length(proof_hash) = 32)
        );
        CREATE TABLE public.auth_source_windows (
          source_hash bytea PRIMARY KEY CHECK (octet_length(source_hash) = 32),
          expires_at timestamptz NOT NULL,
          attempts integer NOT NULL CHECK (attempts BETWEEN 1 AND 10)
        );
        CREATE INDEX ix_auth_source_windows_expires_at ON public.auth_source_windows (expires_at);
        CREATE TABLE public.apple_onboarding_credentials (
          state_hash bytea PRIMARY KEY REFERENCES public.auth_transactions (state_hash)
            ON DELETE CASCADE ON UPDATE RESTRICT,
          ciphertext bytea NOT NULL CHECK (octet_length(ciphertext) BETWEEN 1 AND 16384),
          key_version varchar(64) NOT NULL CHECK (key_version ~ '^[A-Za-z0-9._-]+$')
        );
        CREATE FUNCTION public.usc_apple_onboarding_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
        BEGIN
          PERFORM FROM public.auth_transactions
            WHERE state_hash = NEW.state_hash AND provider = 'apple'
              AND purpose = 'onboarding' AND consumed_at IS NULL
            FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'Apple credential requires a pending Apple onboarding transaction'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$;
        CREATE TRIGGER usc_apple_onboarding_guard BEFORE INSERT OR UPDATE
          ON public.apple_onboarding_credentials FOR EACH ROW
          EXECUTE FUNCTION public.usc_apple_onboarding_guard();
        CREATE INDEX ix_auth_transactions_apple_proof
          ON public.auth_transactions (verified_issuer, verified_subject)
          WHERE provider = 'apple' AND purpose = 'onboarding';
        CREATE INDEX ix_auth_transactions_expires_at
          ON public.auth_transactions (expires_at);
    """)


def downgrade():
    """Allow disposal only if pending credential and revocation state are empty."""
    database = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if (os.environ.get("USC_ALLOW_DISPOSABLE_DOWNGRADE") != "1"
            or not database.startswith("unshaken_foundation_test_")):
        raise RuntimeError("Rollback requires explicit disposable-test authorization.")
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SELECT pg_catalog.pg_advisory_xact_lock(746231901)")
    op.execute("""
        LOCK TABLE public.user_identities, public.auth_transactions,
          public.apple_onboarding_credentials, public.apple_revoked_proofs,
          public.auth_source_windows IN ACCESS EXCLUSIVE MODE;
        DO $$
        BEGIN
          IF EXISTS (SELECT FROM public.apple_onboarding_credentials)
             OR EXISTS (SELECT FROM public.apple_revoked_proofs)
             OR EXISTS (SELECT FROM public.user_identities WHERE provider_revoked_at IS NOT NULL) THEN
            RAISE EXCEPTION 'Apple onboarding downgrade requires empty new authentication state';
          END IF;
        END;
        $$;
        DROP TABLE public.apple_onboarding_credentials, public.apple_revoked_proofs, public.auth_source_windows;
        DROP FUNCTION public.usc_apple_onboarding_guard();
        DROP INDEX public.ix_auth_transactions_expires_at, public.ix_auth_transactions_apple_proof;
        ALTER TABLE public.auth_transactions DROP COLUMN link_session_hash;
        ALTER TABLE public.user_identities DROP COLUMN provider_revoked_at;
    """)
