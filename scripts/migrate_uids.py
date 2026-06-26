"""One-time backfill: stamp a stable ``uid`` into legacy L0 block headers.

Entries written before Phase 3.5 have headers of the form ``## HH:MM:SS · type``
with no ``uid``. This script rewrites each such header to ``## HH:MM:SS · type ·
uid``, minting a fresh uid per entry, so every entry gains the stable identity the
upper layers reference (ADR-001). It is the *one* deliberate, logged rewrite of L0
that the "append-only" contract permits — done now, while the vault is small,
rather than retrofitting ids onto a full journal later.

Properties that make it safe to run:

- **Body-preserving.** Only header *lines* that lack a uid are touched; an entry's
  text is never reserialized or altered — a header line gets ``· uid`` appended,
  nothing else moves.
- **Idempotent.** A header that already carries a uid does not match the legacy
  pattern, so running the script twice stamps nothing the second time.
- **Atomic per file.** Each day-file is rewritten via a temp file + ``os.replace``,
  so an interrupted run can never leave a half-written journal — the source of
  truth is never at risk.

Usage (from the repo root):
    python scripts/migrate_uids.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(_BACKEND))

from memory import vault  # noqa: E402  (import after sys.path setup)

# A legacy header: timestamp + type and nothing after it (no ``· uid``). A header
# that already has a uid carries extra ``· hex`` and so won't match — that is what
# makes the migration idempotent.
_LEGACY_HEADER = re.compile(r"^## (\d{2}:\d{2}:\d{2}) · (\S+)$")


def _stamp_file(path: Path) -> int:
    """Stamp uids into one day-file's legacy headers; return how many it added.

    Reads the file line by line, appends ``· uid`` to every header missing one, and
    writes the result back atomically only if anything changed. Returns 0 for a
    file that was already fully migrated (so a re-run is a no-op).
    """
    lines = path.read_text(encoding="utf-8").split("\n")
    stamped = 0
    for index, line in enumerate(lines):
        if _LEGACY_HEADER.match(line):
            lines[index] = f"{line} · {vault.new_uid()}"
            stamped += 1

    if stamped:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        os.replace(tmp, path)  # atomic on the same filesystem
    return stamped


def main() -> None:
    """Stamp every day-file in the vault and report what changed."""
    directory = vault.journal_dir()
    if not directory.is_dir():
        print("no journal directory yet — nothing to migrate")
        return

    total_files = total_stamped = 0
    for path in sorted(directory.glob("*.md")):
        added = _stamp_file(path)
        if added:
            total_files += 1
            total_stamped += added
            print(f"  {path.name}: stamped {added} entr{'y' if added == 1 else 'ies'}")

    if total_stamped:
        print(f"\nstamped {total_stamped} entries across {total_files} day-file(s).")
        print("Now run `python scripts/reextract.py` to rebuild the database.")
    else:
        print("all entries already have a uid — nothing to do.")


if __name__ == "__main__":
    main()
