"""Write the OpenAPI schema to a file.

The frontend generates its typed client from this, so it is checked in: a
build that regenerates types by importing the Python app would need Python in
the Node toolchain, and CI would silently pass while the two drifted.

    python scripts/dump_openapi.py web/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    target = Path(argv[1] if len(argv) > 1 else "web/openapi.json")

    from careercraft.api.app import create_app

    schema = create_app().openapi()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target} ({len(schema['paths'])} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
