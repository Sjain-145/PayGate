import argparse
import asyncio
import statistics
import time
import uuid

import httpx


async def worker(
    client: httpx.AsyncClient,
    base: str,
    headers: dict,
    customer_id: str,
    n: int,
    latencies: list[float],
    errors: list[int],
) -> None:
    for _ in range(n):
        key = f"load-{uuid.uuid4()}"
        h = {**headers, "Idempotency-Key": key}
        t0 = time.perf_counter()
        try:
            create = await client.post(
                f"{base}/payments",
                headers=h,
                json={
                    "customer_id": customer_id,
                    "amount_minor": 1000,
                    "currency": "INR",
                },
            )
            latencies.append((time.perf_counter() - t0) * 1000)
            if create.status_code != 201:
                errors.append(create.status_code)
                continue
            pid = create.json()["id"]
            t1 = time.perf_counter()
            get = await client.get(f"{base}/payments/{pid}", headers=headers)
            latencies.append((time.perf_counter() - t1) * 1000)
            if get.status_code != 200:
                errors.append(get.status_code)
            t2 = time.perf_counter()
            listed = await client.get(f"{base}/payments?limit=20", headers=headers)
            latencies.append((time.perf_counter() - t2) * 1000)
            if listed.status_code != 200:
                errors.append(listed.status_code)
        except Exception:
            errors.append(0)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--customer-id", required=True)
    parser.add_argument("--vus", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()
    headers = {"Authorization": f"Bearer {args.api_key}"}
    start = time.perf_counter()
    latencies: list[float] = []
    errors: list[int] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        await asyncio.gather(
            *[
                worker(
                    client,
                    args.base,
                    headers,
                    args.customer_id,
                    args.iterations,
                    latencies,
                    errors,
                )
                for _ in range(args.vus)
            ]
        )
    elapsed = time.perf_counter() - start
    total = len(latencies) + len(errors)
    ok = len(latencies)
    latencies_sorted = sorted(latencies)
    def pct(p: float) -> float:
        if not latencies_sorted:
            return 0.0
        idx = min(int(len(latencies_sorted) * p), len(latencies_sorted) - 1)
        return latencies_sorted[idx]

    print(f"duration_s={elapsed:.2f}")
    print(f"requests={ok}")
    print(f"errors={len(errors)}")
    print(f"rps={ok / elapsed:.2f}")
    print(f"error_rate={len(errors) / max(total, 1):.4f}")
    print(f"p50_ms={pct(0.50):.2f}")
    print(f"p95_ms={pct(0.95):.2f}")
    print(f"p99_ms={pct(0.99):.2f}")


if __name__ == "__main__":
    asyncio.run(main())
