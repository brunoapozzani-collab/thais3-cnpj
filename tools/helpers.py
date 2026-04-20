"""
Shared utilities for Debora 3# tools.
All tools import from here for consistent behavior.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Project root is one level up from tools/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = PROJECT_ROOT / ".tmp"
ENV_FILE = PROJECT_ROOT / ".env"


def load_env():
    """Load .env file into os.environ. No dependency on python-dotenv at import time."""
    if not ENV_FILE.exists():
        return
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            os.environ.setdefault(key, value)


def validate_cnpj(cnpj: str) -> bool:
    """
    Validate a CNPJ using the official checksum algorithm.
    Accepts raw digits or formatted (XX.XXX.XXX/XXXX-XX).
    """
    digits = strip_cnpj(cnpj)

    if len(digits) != 14:
        return False

    # Reject all-same-digit CNPJs (e.g. 11111111111111)
    if len(set(digits)) == 1:
        return False

    # First check digit
    weights_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    total = sum(int(digits[i]) * weights_1[i] for i in range(12))
    remainder = total % 11
    check_1 = 0 if remainder < 2 else 11 - remainder

    if int(digits[12]) != check_1:
        return False

    # Second check digit
    weights_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    total = sum(int(digits[i]) * weights_2[i] for i in range(13))
    remainder = total % 11
    check_2 = 0 if remainder < 2 else 11 - remainder

    if int(digits[13]) != check_2:
        return False

    return True


def format_cnpj(cnpj: str) -> str:
    """Format a raw CNPJ string as XX.XXX.XXX/XXXX-XX."""
    d = strip_cnpj(cnpj).ljust(14, "0")
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"


def strip_cnpj(cnpj: str) -> str:
    """Remove all non-digit characters from a CNPJ string."""
    return "".join(c for c in cnpj if c.isdigit())


def parse_args_with_mode(description):
    """
    Create an ArgumentParser with --execute / --dry-run flags.
    Default is dry-run. Returns the parser (caller adds tool-specific args).
    """
    parser = argparse.ArgumentParser(description=description)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Run for real (API calls, file writes)",
    )
    group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview mode — no API calls, no file writes (default)",
    )
    return parser


def save_json(filename, data):
    """
    Save data as JSON to .tmp/<filename>.
    Never overwrites — appends timestamp suffix if file exists.
    """
    TMP_DIR.mkdir(exist_ok=True)
    path = TMP_DIR / filename
    if path.exists():
        stem = path.stem
        suffix = path.suffix
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = TMP_DIR / f"{stem}_{ts}{suffix}"
        path.rename(backup)
        log(f"Existing file backed up to {backup.name}")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"Saved: {path}")
    return path


def load_json(path):
    """Load a JSON file. Returns parsed data or None on error."""
    p = Path(path)
    if not p.exists():
        log(f"File not found: {path}")
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log(f"Error reading {path}: {e}")
        return None


def log(message):
    """Print a timestamped log message to stderr."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {message}", file=sys.stderr)


def ensure_tmp():
    """Ensure .tmp/ directory exists."""
    TMP_DIR.mkdir(exist_ok=True)
