"""Scheduled job: pull results for published posts from the platforms that allow it (currently X).

    python -m app.jobs.pull_metrics            one pass (run it hourly from cron)
    python -m app.jobs.pull_metrics --loop 3600

No AI is used. Idempotent and cheap: each post is read at most four times (1, 3, 7 and 14 days after publishing), and numbers
you entered yourself are never overwritten. See app/analytics.py."""

import argparse
import logging
import time

from sqlalchemy.orm import sessionmaker

from app.analytics import run_pulls
from app.config import get_settings
from app.db import make_engine, prepare_schema
from app.main import build_publishing

log = logging.getLogger("smm.analytics")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--loop", type=int, metavar="SECONDS", help="repeat forever with this pause between passes")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    engine = make_engine(settings.database_url)
    prepare_schema(engine, settings)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    publishing = build_publishing(settings)
    while True:
        outcomes = run_pulls(factory, publishing)
        if outcomes:
            summary = {k: sum(o.status == k for o in outcomes) for k in ("updated", "missing", "forbidden", "retry", "reconnect")}
            log.info("metrics pass: %s", {k: v for k, v in summary.items() if v})
        if not args.loop:
            return
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
