"""Entry point: python -m kudosy"""

from __future__ import annotations

import uvicorn

from kudosy.app import create_app
from kudosy.settings import get_settings


def main() -> None:
    env = get_settings()
    uvicorn.run(
        create_app(),
        host=env.host,
        port=env.port,
        log_config=None,  # we manage logging ourselves
    )


if __name__ == "__main__":
    main()
