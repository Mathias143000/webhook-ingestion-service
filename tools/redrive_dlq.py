from __future__ import annotations

import argparse
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18180")
    parser.add_argument("--api-key", default="supersecret")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    request = urllib.request.Request(
        f"{args.base_url.rstrip('/')}/queue/dlq/redrive?limit={args.limit}",
        method="POST",
        headers={"X-API-KEY": args.api_key},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        print(response.read().decode("utf-8"))


if __name__ == "__main__":
    main()
