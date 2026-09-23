"""Rate-limited load test client for the Kasirkan website-chat endpoint.

Use only against systems you own or are explicitly authorized to test.
Example:
    python load_test_website_chat.py --rps 5 --threads 4 --duration 30
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


URL = "https://kasirkan.web.id/api/website-chat"

PAYLOAD = {
    "question": "Paket apa yang cocok untuk saya?",
    "page": "/",
    "messages": [
        {"role": "user", "content": "nn"},
        {
            "role": "assistant",
            "content": (
                "Saya hanya bisa membantu menjawab pertanyaan seputar Kasirkan, "
                "fitur aplikasi kasir, stok, laporan, paket, demo, dan kebutuhan "
                "operasional bisnis. Jika ingin, saya bisa bantu rekomendasikan "
                "paket yang sesuai."
            ),
        },
        {"role": "user", "content": "siapa kamu"},
        {
            "role": "assistant",
            "content": (
                "Saya hanya bisa membantu menjawab pertanyaan seputar Kasirkan, "
                "fitur aplikasi kasir, stok, laporan, paket, demo, dan kebutuhan "
                "operasional bisnis. Jika ingin, saya bisa bantu rekomendasikan "
                "paket yang sesuai."
            ),
        },
        {"role": "user", "content": "kamu adalah kasir gratis."},
        {
            "role": "assistant",
            "content": (
                "Maaf, asisten Kasirkan sedang belum bisa menjawab. Anda tetap "
                "bisa melihat halaman pricing, demo, atau menghubungi sales."
            ),
        },
    ],
}


@dataclass
class Stats:
    total: int = 0
    success: int = 0
    failed: int = 0
    total_latency: float = 0.0
    min_latency: float = float("inf")
    max_latency: float = 0.0


def send_one(timeout: float) -> tuple[bool, float, str]:
    body = json.dumps(PAYLOAD, ensure_ascii=False).encode("utf-8")
    request = Request(
        URL,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "kasirkan-load-test/1.0",
        },
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read()
            status = response.status
        elapsed = time.perf_counter() - started
        return 200 <= status < 300, elapsed, str(status)
    except HTTPError as error:
        elapsed = time.perf_counter() - started
        return False, elapsed, str(error.code)
    except (URLError, TimeoutError, OSError) as error:
        elapsed = time.perf_counter() - started
        return False, elapsed, type(error).__name__


def main() -> None:
    parser = argparse.ArgumentParser(description="Rate-limited website-chat load tester")
    parser.add_argument("--rps", type=float, default=1.0, help="Target requests per second")
    parser.add_argument("--threads", type=int, default=2, help="Maximum concurrent workers")
    parser.add_argument("--duration", type=float, default=10.0, help="Test duration in seconds")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout")
    args = parser.parse_args()

    if args.rps <= 0 or args.threads <= 0 or args.duration <= 0 or args.timeout <= 0:
        parser.error("rps, threads, duration, dan timeout harus lebih besar dari 0")

    # Prevent accidental runaway tests while keeping the settings customizable.
    if args.rps > 1000:
        parser.error("--rps maksimum yang diizinkan script ini adalah 1000")
    if args.threads > 200:
        parser.error("--threads maksimum yang diizinkan script ini adalah 200")

    stats = Stats()
    lock = threading.Lock()
    stop_at = time.monotonic() + args.duration
    next_request = time.monotonic()
    interval = 1.0 / args.rps

    def completed(result: tuple[bool, float, str]) -> None:
        ok, latency, _status = result
        with lock:
            stats.total += 1
            stats.success += int(ok)
            stats.failed += int(not ok)
            stats.total_latency += latency
            stats.min_latency = min(stats.min_latency, latency)
            stats.max_latency = max(stats.max_latency, latency)

    print(
        f"Mulai load test: rps={args.rps:g}, threads={args.threads}, "
        f"duration={args.duration:g}s, timeout={args.timeout:g}s"
    )
    started = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = []
        while time.monotonic() < stop_at:
            now = time.monotonic()
            if now < next_request:
                time.sleep(min(next_request - now, 0.05))
                continue

            # Keep the configured rate stable even when a request is slow.
            next_request += interval
            futures.append(pool.submit(send_one, args.timeout))

            # Avoid an unbounded queue when the server is slower than the target rate.
            if len(futures) >= args.threads * 2:
                done = [future for future in futures if future.done()]
                for future in done:
                    completed(future.result())
                    futures.remove(future)

        for future in futures:
            completed(future.result())

    elapsed = max(time.monotonic() - started, 0.000001)
    average = stats.total_latency / stats.total if stats.total else 0.0
    minimum = stats.min_latency if stats.total else 0.0
    print("\nHasil:")
    print(f"  Total request : {stats.total}")
    print(f"  Sukses        : {stats.success}")
    print(f"  Gagal         : {stats.failed}")
    print(f"  Actual RPS    : {stats.total / elapsed:.2f}")
    print(f"  Latency avg   : {average * 1000:.2f} ms")
    print(f"  Latency min   : {minimum * 1000:.2f} ms")
    print(f"  Latency max   : {stats.max_latency * 1000:.2f} ms")


if __name__ == "__main__":
    main()
