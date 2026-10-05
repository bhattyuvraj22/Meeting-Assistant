"""One run.log per run: stage timings, warnings, token usage. API keys are never passed to the logger."""
import logging

# creates a logger for one pipeline run that writes to <out_dir>/run.log. only Orchestrator.py calls get_run_logger .

def get_run_logger(out_dir, run_id):
    logger = logging.getLogger(f"meeting_assistant.{run_id}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.FileHandler(str(out_dir / "run.log"), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger

# It closes the log file and detaches each handler.

def close_run_logger(logger):
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)
