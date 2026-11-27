"""Add authentication storage without rewriting existing identities."""

import os

from alembic import op

revision = "0004_auth_storage"
down_revision = "0003_workout_follow_up"
branch_labels = None
depends_on = None


def execute(sql):
    """Execute frozen PostgreSQL DDL within the migration transaction."""
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(sql)


def upgrade():
    """Install ownership, lifetime, and credential shape constraints."""
    execute("""
        SET LOCAL lock_timeout = '5s';
        SELECT pg_catalog.pg_advisory_xact_lock(746231901);
        LOCK TABLE public.user_identities IN ACCESS EXCLUSIVE MODE;
        DO $$
        BEGIN
          IF EXISTS (SELECT FROM public.user_identities WHERE provider NOT IN ('google', 'microsoft')) THEN
            RAISE EXCEPTION 'Authentication preflight found unsupported legacy identity providers';
          END IF;
        END;
        $$;
        ALTER TABLE public.user_identities
          DROP CONSTRAINT ck_user_identities_1,
          ADD CONSTRAINT ck_user_identities_1 CHECK (provider IN ('google', 'apple', 'microsoft')),
          ADD CONSTRAINT uq_auth_identity_owner UNIQUE (id, user_id),
          ADD CONSTRAINT uq_auth_identity_provider UNIQUE (id, provider);

        CREATE FUNCTION public.usc_auth_identity_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF (NEW.id, NEW.user_id, NEW.provider, NEW.issuer, NEW.subject)
               IS DISTINCT FROM (OLD.id, OLD.user_id, OLD.provider, OLD.issuer, OLD.subject) THEN
              RAISE EXCEPTION 'Identity ownership and proof cannot change' USING ERRCODE = '23514';
            END IF;
          ELSIF NEW.provider = 'microsoft' THEN
            RAISE EXCEPTION 'New Microsoft identities are disabled' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$;
        CREATE TRIGGER usc_auth_identity_guard BEFORE INSERT OR UPDATE ON public.user_identities
          FOR EACH ROW EXECUTE FUNCTION public.usc_auth_identity_guard();

        CREATE TABLE public.auth_sessions (
          token_hash bytea PRIMARY KEY CHECK (octet_length(token_hash) = 32),
          user_id uuid NOT NULL,
          identity_id uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
          last_seen_at timestamptz NOT NULL DEFAULT statement_timestamp(),
          revoked_at timestamptz,
          CHECK (isfinite(created_at) AND isfinite(last_seen_at)
            AND last_seen_at >= created_at AND last_seen_at <= created_at + interval '8 hours'),
          CHECK (revoked_at IS NULL OR (isfinite(revoked_at) AND revoked_at >= created_at)),
          FOREIGN KEY (identity_id, user_id) REFERENCES public.user_identities (id, user_id)
            ON DELETE RESTRICT ON UPDATE RESTRICT
        );

        CREATE INDEX ix_auth_sessions_identity_id ON public.auth_sessions (identity_id);
        CREATE INDEX ix_auth_sessions_user_id ON public.auth_sessions (user_id);

        CREATE TABLE public.auth_transactions (
          binding_hash bytea NOT NULL CHECK (octet_length(binding_hash) = 32),
          state_hash bytea PRIMARY KEY CHECK (octet_length(state_hash) = 32),
          nonce_hash bytea NOT NULL CHECK (octet_length(nonce_hash) = 32),
          provider varchar(20) NOT NULL CHECK (provider IN ('google', 'apple')),
          purpose varchar(20) NOT NULL CHECK (purpose IN ('login', 'link', 'onboarding')),
          verified_issuer varchar(512),
          verified_subject varchar(512),
          user_id uuid REFERENCES public.users (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
          return_path varchar(512) NOT NULL CHECK (left(return_path, 1) = '/' AND left(return_path, 2) <> '//' AND strpos(return_path, chr(92)) = 0 AND return_path !~ '[[:cntrl:]]'),
          created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
          expires_at timestamptz NOT NULL,
          consumed_at timestamptz,
          CHECK ((purpose = 'onboarding' AND verified_issuer IS NOT NULL AND verified_subject IS NOT NULL
            AND btrim(verified_issuer) <> '' AND btrim(verified_subject) <> '')
            OR (purpose <> 'onboarding' AND verified_issuer IS NULL AND verified_subject IS NULL)),
          CHECK ((purpose = 'link') = (user_id IS NOT NULL)),
          CHECK (isfinite(created_at) AND expires_at > created_at
            AND expires_at <= created_at + interval '5 minutes'),
          CHECK (consumed_at IS NULL OR (consumed_at >= created_at AND consumed_at < expires_at))
        );

        CREATE INDEX ix_auth_transactions_user_id ON public.auth_transactions (user_id);

        CREATE FUNCTION public.usc_auth_transaction_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
        DECLARE
          consumption_time timestamptz;
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.consumed_at IS NOT NULL THEN
              RAISE EXCEPTION 'New authentication transactions must be unconsumed' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
          END IF;

          -- Check expiry when the row is actually being consumed.
          consumption_time := clock_timestamp();
          IF OLD.consumed_at IS NOT NULL OR OLD.expires_at <= consumption_time
             OR (to_jsonb(NEW) - 'consumed_at') IS DISTINCT FROM (to_jsonb(OLD) - 'consumed_at')
             OR NEW.consumed_at IS NULL THEN
            RAISE EXCEPTION 'Authentication transaction cannot be consumed' USING ERRCODE = '23514';
          ELSE
            NEW.consumed_at := consumption_time;
          END IF;
          RETURN NEW;
        END;
        $$;
        CREATE TRIGGER usc_auth_transaction_guard BEFORE INSERT OR UPDATE ON public.auth_transactions
          FOR EACH ROW EXECUTE FUNCTION public.usc_auth_transaction_guard();

        CREATE TABLE public.apple_revocation_credentials (
          identity_id uuid PRIMARY KEY,
          provider varchar(20) NOT NULL DEFAULT 'apple' CHECK (provider = 'apple'),
          ciphertext bytea NOT NULL CHECK (octet_length(ciphertext) BETWEEN 1 AND 16384),
          key_version varchar(64) NOT NULL CHECK (key_version ~ '^[A-Za-z0-9._-]+$'),
          FOREIGN KEY (identity_id, provider) REFERENCES public.user_identities (id, provider)
            ON DELETE RESTRICT ON UPDATE RESTRICT
        );
    """)


def downgrade():
    """Restore the old schema only when the new storage is empty."""
    database = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if (os.environ.get("USC_ALLOW_DISPOSABLE_DOWNGRADE") != "1"
            or not database.startswith("unshaken_foundation_test_")):
        raise RuntimeError("Rollback is allowed only with explicit disposable-test authorization.")
    execute("""
        SET LOCAL lock_timeout = '5s';
        SELECT pg_catalog.pg_advisory_xact_lock(746231901);
        LOCK TABLE public.user_identities, public.auth_sessions, public.auth_transactions,
          public.apple_revocation_credentials IN ACCESS EXCLUSIVE MODE;
        DO $$
        BEGIN
          IF EXISTS (SELECT FROM public.user_identities WHERE provider = 'apple')
            OR EXISTS (SELECT FROM public.auth_sessions)
            OR EXISTS (SELECT FROM public.auth_transactions)
            OR EXISTS (SELECT FROM public.apple_revocation_credentials) THEN
            RAISE EXCEPTION 'Auth storage downgrade requires empty new storage and no Apple identities';
          END IF;
        END;
        $$;
        DROP TABLE public.apple_revocation_credentials, public.auth_transactions, public.auth_sessions;
        DROP FUNCTION public.usc_auth_transaction_guard();
        DROP TRIGGER usc_auth_identity_guard ON public.user_identities;
        DROP FUNCTION public.usc_auth_identity_guard();
        ALTER TABLE public.user_identities
          DROP CONSTRAINT uq_auth_identity_owner,
          DROP CONSTRAINT uq_auth_identity_provider,
          DROP CONSTRAINT ck_user_identities_1,
          ADD CONSTRAINT ck_user_identities_1 CHECK (provider IN ('google', 'microsoft'));
    """)
