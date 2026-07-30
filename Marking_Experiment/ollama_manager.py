"""Ollama process and model helpers for the Marking Experiment UI."""

from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from typing import List, Optional


OLLAMA_HOST = "127.0.0.1:11434"
OLLAMA_BASE_URL = f"http://{OLLAMA_HOST}"


def stop_ollama_instances() -> None:
    """Stop currently running Ollama processes on Windows."""
    subprocess.run(
        ["taskkill", "/F", "/IM", "ollama.exe", "/T"],
        text=True,
        capture_output=True,
        timeout=10,
    )


def list_installed_models() -> List[str]:
    """Return locally installed Ollama model names."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []

    models: List[str] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


def start_ollama_server() -> Optional[subprocess.Popen]:
    """Start an Ollama server process and return the process handle if started."""
    env = os.environ.copy()
    env["OLLAMA_HOST"] = OLLAMA_HOST
    os.environ["OLLAMA_HOST"] = OLLAMA_HOST
    os.environ["OLLAMA_HTTP_BASE_URL"] = OLLAMA_BASE_URL

    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW

    try:
        proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except OSError:
        return None

    if not wait_for_ollama(timeout_seconds=30):
        if proc.poll() is None:
            proc.terminate()
        return None
    return proc


def wait_for_ollama(timeout_seconds: int = 30) -> bool:
    """Wait until the local Ollama HTTP API is reachable."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False
