from __future__ import annotations

import argparse
import pathlib
import subprocess


def run(command: list[str], *, cwd: pathlib.Path) -> str:
    completed = subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)
    return completed.stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="artifacts/evidence")
    args = parser.parse_args()

    root = pathlib.Path(__file__).resolve().parents[1]
    output_dir = root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "compose-ps.txt").write_text(
        run(["docker", "compose", "ps"], cwd=root),
        encoding="utf-8",
    )
    (output_dir / "compose-logs.txt").write_text(
        run(["docker", "compose", "logs", "--no-color"], cwd=root),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
