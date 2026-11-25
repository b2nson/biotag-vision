"""Material database: code -> display name, default bin, note."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional


class Materials:
    def __init__(self, path: Optional[Path] = None, local_overrides: Optional[Dict[str, str]] = None):
        path = path or Path(__file__).with_name("materials.json")
        with open(path, "r", encoding="utf-8") as fh:
            self._db = json.load(fh)
        self._overrides = {k.upper(): v.upper() for k, v in (local_overrides or {}).items()}

    def known(self, code: str) -> bool:
        return code.upper() in self._db

    def name(self, code: str) -> str:
        return self._db.get(code.upper(), {}).get("name", code)

    def note(self, code: str) -> str:
        return self._db.get(code.upper(), {}).get("note", "")

    def bin_for(self, code: str, tag_bin: Optional[str] = None) -> str:
        """Local rules win, then the bin printed in the tag, then the default."""
        code = code.upper()
        if code in self._overrides:
            return self._overrides[code]
        if tag_bin in ("R", "C", "L"):
            return tag_bin
        return self._db.get(code, {}).get("bin", "L")
