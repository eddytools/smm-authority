"""Scheduled job: post every approved, Scheduled post whose time has come.

    python -m app.jobs.publish_due            one pass (run it every minute from cron)
    python -m app.jobs.publish_due --loop 30  keep running, one pass every 30 seconds (handy for local development)

No AI is used. Idempotent: posts are claimed atomically, so overlapping runs never double-post."""

import argparse
import logging
import time

from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import init_schema, make_engine
from app.main import build_publishing
from app.publishing import run_due

log = logging.getLogger("smm.publish")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--loop", type=int, metavar="SECONDS", help="repeat forever with this pause between passes")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    engine = make_engine(settings.database_url)
    init_schema(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    publishing = build_publishing(settings)
    while True:
        outcomes = run_due(factory, publishing)
        if outcomes:
            summary = {k: sum(o.status == k for o in outcomes) for k in ("published", "retry", "failed", "reconnect", "skipped")}
            log.info("publish pass: %s", {k: v for k, v in summary.items() if v})
        if not args.loop:
            return
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
