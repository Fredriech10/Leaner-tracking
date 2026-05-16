"""Logging and configuration for Marking Experiment."""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

# Default configuration
DEFAULT_LOG_LEVEL = os.environ.get("MARKING_LOG_LEVEL", "INFO").upper()
DEFAULT_LOG_FILE = Path(os.environ.get("MARKING_LOG_FILE", "marking_experiment.log"))

# Default timeout for LLM calls
DEFAULT_LLM_TIMEOUT_SECONDS = int(os.environ.get("MARKING_LLM_TIMEOUT", "120"))

# Default Ollama settings
DEFAULT_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
DEFAULT_OLLAMA_MODEL = os.environ.get("MARKING_OLLAMA_MODEL", "phi3:instruct")

# Default OpenAI settings
DEFAULT_OPENAI_MODEL = os.environ.get("MARKING_OPENAI_MODEL", "gpt-4o-mini")

# Tolerances for numeric comparisons
NUMERIC_TOLERANCE_PT = 0.5  # Points
NUMERIC_TOLERANCE_CM = 0.05  # Centimeters
NUMERIC_TOLERANCE_LINES = 0.1  # Lines


def configure_logging(level: str = DEFAULT_LOG_LEVEL, log_file: Path | str | None = DEFAULT_LOG_FILE) -> None:
    """Configure logging for Marking Experiment.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Path to log file, or None to disable file logging.
    """
    # Root logger configuration
    logger = logging.getLogger()
    logger.setLevel(level)
    
    # Console handler (always enabled)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # File handler (if path provided)
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_handler = logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=5,
            )
            file_handler.setLevel(level)
            file_formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning(f"Could not set up file logging to {log_file}: {e}")


# Call this once when module is imported
try:
    configure_logging(level=DEFAULT_LOG_LEVEL, log_file=DEFAULT_LOG_FILE)
except Exception as e:
    print(f"Warning: Could not configure logging: {e}")
