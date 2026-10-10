import argparse
import logging
import signal
import time

from .clients import Collector, HTTP, Model
from .config import Settings
from .storage import Store

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, settings: Settings, store: Store, collector: Collector, model: Model):
        self.settings, self.store, self.collector, self.model = settings, store, collector, model

    def once(self):
        claim = self.store.claim()
        if not claim:
            return False
        try:
            snapshot = self.store.snapshot(claim["incident_id"])
            evidence = self.collector.collect(snapshot)
            assessment = self.model.assess(evidence)
            self.store.complete(claim, snapshot, assessment, evidence)
            log.info("Investigation processed: incident=%s revision=%s", snapshot["id"], snapshot["revision"])
        except Exception as exc:
            # Never log requests, credentials, model content, or database URLs.
            self.store.fail(claim, type(exc).__name__)
            log.warning("Investigation retry/failure: incident=%s error=%s", claim["incident_id"], type(exc).__name__)
        return True

    def review(self):
        data = self.store.review_data()
        if data["rules"]:
            self.store.save_review(data, self.model.review(data))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--review", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings()
    settings.validate()
    store = Store(settings)
    store.initialize()
    http = HTTP(settings)
    worker = Worker(settings, store, Collector(settings, http), Model(settings, http))
    if args.review:
        worker.review()
        return
    if args.once:
        worker.once()
        return
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    last_review = time.monotonic()
    last_wait_log = 0
    while not stopping:
        if not worker.model.available():
            if time.monotonic()-last_wait_log >= 30:
                log.info("Waiting for configured local Ollama model; jobs remain queued")
                last_wait_log = time.monotonic()
            time.sleep(1)
            continue
        if not worker.once():
            time.sleep(1)
        if settings.review_seconds > 0 and time.monotonic()-last_review >= settings.review_seconds:
            try:
                worker.review()
            except Exception as exc:
                log.warning("Rule review failed: error=%s", type(exc).__name__)
            last_review = time.monotonic()
    http.client.close()


if __name__ == "__main__":
    main()
