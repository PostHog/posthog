# ruff: noqa: T201
"""
Test script: prove that a locked product database doesn't bring down Django.

What it does:
1. Opens a transaction on posthog_visual_review and locks a table with ACCESS EXCLUSIVE
2. Fires concurrent HTTP requests:
   - One to a visual_review endpoint (should hang/timeout)
   - One to a core PostHog endpoint (should succeed)
3. Reports which succeeded and which blocked

Run with Django dev server up:
  python scripts/test_db_isolation.py
"""

from __future__ import annotations

import sys
import time
import threading
import subprocess

import psycopg

VISUAL_REVIEW_DB = "posthog_visual_review"
PG_HOST = "localhost"
PG_PORT = 5432
PG_USER = "posthog"
PG_PASSWORD = "posthog"

# Adjust these to your local dev server
BASE_URL = "http://localhost:8000"
API_KEY = "phx_dev_local_test_api_key_1234567890abcdef"
# A core endpoint that doesn't touch visual_review at all
CORE_ENDPOINT = f"{BASE_URL}/api/projects/"
# A visual_review endpoint that will try to query the locked DB
VR_ENDPOINT = f"{BASE_URL}/api/projects/1/visual_review/repos/"

LOCK_DURATION = 15  # seconds to hold the lock


def hold_exclusive_lock(ready_event: threading.Event) -> None:
    """Open a transaction that locks the visual_review_repo table exclusively."""
    print(f"[locker] Connecting to {VISUAL_REVIEW_DB}...")
    with psycopg.connect(
        dbname=VISUAL_REVIEW_DB,
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
    ) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("LOCK TABLE visual_review_repo IN ACCESS EXCLUSIVE MODE")
            print(f"[locker] Lock acquired on visual_review_repo. Holding for {LOCK_DURATION}s...")
            ready_event.set()
            time.sleep(LOCK_DURATION)
        conn.rollback()
    print("[locker] Lock released.")


def timed_request(label: str, url: str, timeout: int = 10) -> dict:
    """Make an HTTP request and return timing + status."""
    start = time.monotonic()
    try:
        result = subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "-H",
                f"Authorization: Bearer {API_KEY}",
                "--max-time",
                str(timeout),
                url,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
        elapsed = time.monotonic() - start
        status_code = result.stdout.strip()
        return {"label": label, "status": status_code, "elapsed": f"{elapsed:.2f}s", "error": None}
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return {"label": label, "status": "TIMEOUT", "elapsed": f"{elapsed:.2f}s", "error": "timed out"}
    except Exception as e:
        elapsed = time.monotonic() - start
        return {"label": label, "status": "ERROR", "elapsed": f"{elapsed:.2f}s", "error": str(e)}


def main() -> None:
    lock_ready = threading.Event()

    # Start the lock holder in a background thread
    lock_thread = threading.Thread(target=hold_exclusive_lock, args=(lock_ready,), daemon=True)
    lock_thread.start()

    # Wait for lock to be acquired
    lock_ready.wait(timeout=10)
    if not lock_ready.is_set():
        print("ERROR: Failed to acquire lock")
        sys.exit(1)

    print()
    print("Lock is held. Firing requests...")
    print()

    # Fire both requests concurrently
    results: list[dict] = []

    def do_request(label: str, url: str) -> None:
        r = timed_request(label, url, timeout=8)
        results.append(r)

    t1 = threading.Thread(target=do_request, args=("CORE (api/projects/)", CORE_ENDPOINT))
    t2 = threading.Thread(target=do_request, args=("VISUAL_REVIEW (repos/)", VR_ENDPOINT))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    for r in results:
        status_display = r["status"]
        if r["error"]:
            status_display = f"{r['status']} ({r['error']})"
        print(f"  {r['label']:40s} → {status_display:20s} ({r['elapsed']})")
    print("=" * 60)
    print()

    # Interpret
    core_result = next((r for r in results if "CORE" in r["label"]), None)
    vr_result = next((r for r in results if "VISUAL_REVIEW" in r["label"]), None)

    if core_result and core_result["status"] not in ("TIMEOUT", "ERROR"):
        print("PASS: Core endpoint responded while visual_review DB was locked")
    else:
        print("FAIL: Core endpoint was blocked by visual_review DB lock")

    if vr_result and vr_result["status"] in ("TIMEOUT", "ERROR", "500", "000"):
        print("EXPECTED: Visual review endpoint was blocked/errored (DB locked)")
    else:
        print(f"UNEXPECTED: Visual review endpoint returned {vr_result['status'] if vr_result else 'N/A'}")

    # Wait for lock to release
    lock_thread.join(timeout=LOCK_DURATION + 5)


if __name__ == "__main__":
    main()
