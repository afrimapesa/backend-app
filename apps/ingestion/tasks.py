from celery import shared_task

from .registry import get_adapter


@shared_task(name="ingestion.run_adapter", ignore_result=True)
def run_adapter(source: str) -> str:
    """Run one adapter by source name. Failures are recorded in ingestion_runs, not raised."""
    run = get_adapter(source)().run()
    return run.status
