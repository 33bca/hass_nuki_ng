"""Tests for the device registry identifier migration.

No Home Assistant installation required: `plan_identifier_migration` is pure,
so `conftest.py` loads the module against a stub `constants` and the planning
half can be exercised directly.
"""

from __future__ import annotations

from conftest import migration

DOMAIN = "nuki_ng"
LOCK_ID = 824523165
BRIDGE_ID = 485731010

DeviceRow = migration.DeviceRow
plan = migration.plan_identifier_migration


def ids(*pairs):
    return frozenset(pairs)


class TestIdentifierMapping:
    def test_legacy_lock_domain_moves_to_integration_domain(self):
        assert migration.migrate_identifier(("id", LOCK_ID)) == (DOMAIN, LOCK_ID)

    def test_web_identifier_gets_prefixed(self):
        """Lock and Web API share the numeric id — without a prefix the merged
        namespace would collide them into one device."""
        assert migration.migrate_identifier(("web_id", LOCK_ID)) == (
            DOMAIN,
            f"web_{LOCK_ID}",
        )

    def test_current_identifiers_are_left_alone(self):
        assert migration.migrate_identifier((DOMAIN, LOCK_ID)) == (DOMAIN, LOCK_ID)

    def test_foreign_identifiers_are_left_alone(self):
        assert migration.migrate_identifier(("mqtt", "x")) == ("mqtt", "x")


class TestNothingToDo:
    def test_clean_install_produces_no_plan(self):
        devices = [
            DeviceRow("d1", ids((DOMAIN, LOCK_ID))),
            DeviceRow("d2", ids((DOMAIN, BRIDGE_ID))),
            DeviceRow("d3", ids((DOMAIN, f"web_{LOCK_ID}")), via_device_id="d1"),
        ]
        assert plan(devices).is_empty

    def test_empty_registry(self):
        assert plan([]).is_empty


class TestRenameOnly:
    """Upgrading straight from a pre-fix version: no duplicate exists yet."""

    def test_lone_legacy_device_is_renamed_in_place(self):
        devices = [DeviceRow("d1", ids(("id", LOCK_ID)), entity_ids=("lock.a",))]
        got = plan(devices)
        assert got.merges == ()
        assert len(got.renames) == 1
        assert got.renames[0].device_id == "d1"
        assert got.renames[0].new_identifiers == ids((DOMAIN, LOCK_ID))

    def test_rename_keeps_unrelated_identifiers(self):
        devices = [DeviceRow("d1", ids(("id", LOCK_ID), ("mqtt", "keepme")))]
        assert plan(devices).renames[0].new_identifiers == ids(
            (DOMAIN, LOCK_ID), ("mqtt", "keepme")
        )


class TestDuplicateInTheWild:
    """The real state on BGW29: the fixed release created the new device and
    left the old one behind, empty but still parenting the Web API device."""

    def _registry(self):
        return [
            # stale, no entities, but Web API hangs off it
            DeviceRow("stale_lock", ids(("id", LOCK_ID))),
            # the live one
            DeviceRow(
                "live_lock",
                ids((DOMAIN, LOCK_ID)),
                entity_ids=("lock.nuki_zuhause_lock", "sensor.nuki_zuhause_battery"),
            ),
            DeviceRow("stale_bridge", ids(("id", BRIDGE_ID)),
                      entity_ids=("sensor.nuki_bridge_device_power",)),
            DeviceRow("live_bridge", ids((DOMAIN, BRIDGE_ID))),
            DeviceRow(
                "web",
                ids(("web_id", LOCK_ID)),
                via_device_id="stale_lock",
                entity_ids=("switch.nuki_zuhause_authorization_sonja",),
            ),
        ]

    def test_stale_lock_is_merged_not_renamed(self):
        """Renaming would collide with live_lock and raise in the registry."""
        got = plan(self._registry())
        merge = next(m for m in got.merges if m.source_device_id == "stale_lock")
        assert merge.target_device_id == "live_lock"
        assert not any(r.device_id == "stale_lock" for r in got.renames)

    def test_web_device_is_repointed_to_the_surviving_parent(self):
        merge = next(
            m for m in plan(self._registry()).merges
            if m.source_device_id == "stale_lock"
        )
        assert merge.repoint_device_ids == ("web",)

    def test_bridge_entities_are_carried_over(self):
        """Powercalc sensors sit on the stale bridge — they must not be dropped."""
        merge = next(
            m for m in plan(self._registry()).merges
            if m.source_device_id == "stale_bridge"
        )
        assert merge.target_device_id == "live_bridge"
        assert merge.move_entity_ids == ("sensor.nuki_bridge_device_power",)

    def test_web_device_itself_is_renamed(self):
        """Nothing owns (DOMAIN, web_<id>) yet, so it is a plain rename."""
        got = plan(self._registry())
        rename = next(r for r in got.renames if r.device_id == "web")
        assert rename.new_identifiers == ids((DOMAIN, f"web_{LOCK_ID}"))

    def test_live_devices_are_untouched(self):
        got = plan(self._registry())
        touched = {r.device_id for r in got.renames} | {
            m.source_device_id for m in got.merges
        }
        assert "live_lock" not in touched and "live_bridge" not in touched

    def test_five_rows_collapse_to_three(self):
        devices = self._registry()
        got = plan(devices)
        removed = {m.source_device_id for m in got.merges}
        assert len(devices) - len(removed) == 3


class TestIdempotence:
    def test_second_run_is_a_no_op(self):
        """The migration runs on every setup, so it must settle after one pass."""
        devices = [
            DeviceRow("stale", ids(("id", LOCK_ID))),
            DeviceRow("live", ids((DOMAIN, LOCK_ID)), entity_ids=("lock.a",)),
            DeviceRow("web", ids(("web_id", LOCK_ID)), via_device_id="stale"),
        ]
        after = apply_plan(devices, plan(devices))
        assert plan(after).is_empty

    def test_applied_result_has_the_expected_shape(self):
        devices = [
            DeviceRow("stale", ids(("id", LOCK_ID))),
            DeviceRow("live", ids((DOMAIN, LOCK_ID)), entity_ids=("lock.a",)),
            DeviceRow("web", ids(("web_id", LOCK_ID)), via_device_id="stale"),
        ]
        after = {d.device_id: d for d in apply_plan(devices, plan(devices))}
        assert set(after) == {"live", "web"}
        assert after["web"].via_device_id == "live"
        assert after["web"].identifiers == ids((DOMAIN, f"web_{LOCK_ID}"))


def apply_plan(devices, migration_plan):
    """In-memory stand-in for the registry, so idempotence is testable."""
    rows = {d.device_id: d for d in devices}

    for rename in migration_plan.renames:
        old = rows[rename.device_id]
        rows[rename.device_id] = DeviceRow(
            old.device_id, rename.new_identifiers, old.via_device_id, old.entity_ids
        )

    for merge in migration_plan.merges:
        target = rows[merge.target_device_id]
        rows[merge.target_device_id] = DeviceRow(
            target.device_id,
            target.identifiers,
            target.via_device_id,
            target.entity_ids + merge.move_entity_ids,
        )
        for child_id in merge.repoint_device_ids:
            child = rows[child_id]
            rows[child_id] = DeviceRow(
                child.device_id,
                child.identifiers,
                merge.target_device_id,
                child.entity_ids,
            )
        del rows[merge.source_device_id]

    return list(rows.values())
