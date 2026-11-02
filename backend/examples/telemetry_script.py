"""Demonstrate a simulated database read; no PostgreSQL connection is made."""

import argparse
from time import perf_counter
from app.telemetry import initialize, log_event, operation_span, record_operation, shutdown


def run_simulated_read(fail: bool = False) -> bool:
    """Record a clearly mocked success or failure using shared telemetry."""
    start = perf_counter()
    with operation_span("database"):
        outcome = "error" if fail else "success"
        log_event("operation.failed" if fail else "operation.completed", operation="database", outcome=outcome)
        record_operation("database", outcome, perf_counter() - start)
    return not fail


def main() -> int:
    """Run the mock read and flush telemetry before the short-lived process exits."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fail", action="store_true", help="Demonstrate a controlled failure")
    args = parser.parse_args()
    initialize(service="unshaken-script")
    try:
        success = run_simulated_read(args.fail)
        print("Simulated database read:", "success" if success else "controlled failure")
        return 0 if success else 1
    finally:
        shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
