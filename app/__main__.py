"""Run the app as a single service: ``python -m app``."""

from __future__ import annotations

import os

import uvicorn

from app.config import Settings


def main() -> None:
    settings = Settings.from_env()
    port = int(os.environ.get("PORT", settings.port))
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
