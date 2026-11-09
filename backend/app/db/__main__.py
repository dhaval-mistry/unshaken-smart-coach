"""Usage (from backend/):  uv run python -m app.db plan | upgrade --approve-target HOST:PORT/DB"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.exc import OperationalError

from app.db.config import ConfigError, describe_target, get_database_url
from app.db.migrate import ApprovalError, apply_upgrade, build_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.db")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="show target, current version and planned changes (read-only)")
    up = sub.add_parser("upgrade", help="apply pending migrations to the approved target")
    up.add_argument("--approve-target", metavar="HOST:PORT/DATABASE",
                    help="the owner-approved target exactly as printed by 'plan'")
    args = parser.parse_args(argv)
    try:
        url = get_database_url()
        if args.command == "plan":
            print(build_plan(url))
        else:
            print(apply_upgrade(url, args.approve_target))
    except (ConfigError, ApprovalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OperationalError:
        # Driver details are deliberately not printed; check the target and
        # credentials in your private .env.
        print(f"error: could not connect to {describe_target(url)} as user "
              f"'{url.username}'. Check the host, port, database, user and password "
              f"in your private .env (a changed .env does not change an existing "
              f"database's password).", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
