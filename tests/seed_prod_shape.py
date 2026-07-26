#!/usr/bin/env python3
"""Seed a test instance's registries with the duplicate shape seen in the wild.

Run with Home Assistant stopped. Clones the two current nuki_ng devices into
legacy ("id", …) rows, moves one entity onto the legacy bridge and points the
Web API device back at the legacy lock via ("web_id", …) — reproducing the
five-row constellation that a real, long-running install ends up with.

    python3 seed_prod_shape.py /path/to/config [--dry-run]

Only ever point this at a test instance.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

DOMAIN = "nuki_ng"
MOVE_ENTITY = "button.nuki_bridge_reboot"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def save(path: Path, data: dict) -> None:
    shutil.copy(path, path.with_suffix(path.suffix + ".bak-seed"))
    path.write_text(json.dumps(data, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    dev_path = args.config / ".storage" / "core.device_registry"
    ent_path = args.config / ".storage" / "core.entity_registry"
    devices = load(dev_path)
    entities = load(ent_path)

    rows = devices["data"]["devices"]

    def find(identifier):
        for row in rows:
            if [list(i) for i in row["identifiers"]] == [list(identifier)]:
                return row
        return None

    lock = find((DOMAIN, 824523165))
    bridge = find((DOMAIN, 485731010))
    web = find((DOMAIN, "web_824523165"))
    if not (lock and bridge and web):
        print("Expected nuki_ng devices not found — already seeded?")
        return 1

    def legacy_clone(src: dict, new_id: str, identifier) -> dict:
        row = json.loads(json.dumps(src))
        row["id"] = new_id
        row["identifiers"] = [list(identifier)]
        row["via_device_id"] = None
        row["area_id"] = None
        return row

    seed_lock = legacy_clone(lock, "seedlock0000000000000000000000ab", ("id", 824523165))
    seed_bridge = legacy_clone(bridge, "seedbridge000000000000000000000c", ("id", 485731010))
    rows.extend([seed_lock, seed_bridge])

    # Web API back onto the legacy scheme, parented by the legacy lock.
    web["identifiers"] = [["web_id", 824523165]]
    web["via_device_id"] = seed_lock["id"]

    # Give the legacy bridge an entity, so the merge has something to carry
    # (mirrors the Powercalc sensors sitting on the stale bridge in production).
    moved = None
    for ent in entities["data"]["entities"]:
        if ent["entity_id"] == MOVE_ENTITY:
            ent["device_id"] = seed_bridge["id"]
            moved = ent["entity_id"]
            break

    print(f"devices: {len(rows) - 2} -> {len(rows)}")
    print(f"  + {seed_lock['id']}  ('id', 824523165)   no entities")
    print(f"  + {seed_bridge['id']}  ('id', 485731010)   entity: {moved or 'none'}")
    print(f"  ~ {web['id']}  -> ('web_id', 824523165), via_device {seed_lock['id']}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    save(dev_path, devices)
    save(ent_path, entities)
    print("\nwritten, backups kept as *.bak-seed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
