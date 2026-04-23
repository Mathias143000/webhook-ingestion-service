from __future__ import annotations

import pathlib
import shutil


def main() -> None:
    root = pathlib.Path(__file__).resolve().parents[1]
    env_file = root / ".env"
    example = root / ".env.example"
    if not env_file.exists():
        shutil.copy(example, env_file)
        print("Created .env from .env.example")
    else:
        print(".env already exists")


if __name__ == "__main__":
    main()
