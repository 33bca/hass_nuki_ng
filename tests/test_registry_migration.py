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


# ---------------------------------------------------------------------------
#  0.6.3: one device per lock
# ---------------------------------------------------------------------------

EntityRow = migration.EntityRow
web_plan = migration.plan_web_device_merge
WEB = f"web_{LOCK_ID}"


class TestWebDeviceMerge:
    """The 0.6.2 shape: lock device + "Nuki Web" child holding the auth switches."""

    def _registry(self, *, web_area="znowhere", lock_area="front_porch",
                  web_disabled=False, lock_disabled=False):
        devices = [
            DeviceRow("lock", ids((DOMAIN, LOCK_ID)), area_id=lock_area,
                      disabled=lock_disabled,
                      entity_ids=("lock.front_door", "sensor.front_door_battery")),
            DeviceRow("web", ids((DOMAIN, WEB)), via_device_id="lock",
                      area_id=web_area, disabled=web_disabled,
                      entity_ids=("switch.agency_8194", "switch.keypad_27191")),
            DeviceRow("bridge", ids((DOMAIN, BRIDGE_ID))),
        ]
        return devices

    def test_auth_switches_move_to_the_lock_device(self):
        got = web_plan(self._registry(), {})
        assert len(got.merges) == 1 and got.renames == ()
        m = got.merges[0]
        assert (m.source_device_id, m.target_device_id) == ("web", "lock")
        assert m.move_entity_ids == ("switch.agency_8194", "switch.keypad_27191")

    def test_entities_keep_the_area_they_had(self):
        """No own area: they showed the Web device's area; pin it so nothing moves."""
        entities = {"switch.keypad_27191": EntityRow("switch.keypad_27191", area_id="hall")}
        m = web_plan(self._registry(), entities).merges[0]
        assert m.keep_area == (("switch.agency_8194", "znowhere"),)

    def test_same_area_needs_no_pin(self):
        m = web_plan(self._registry(web_area="casa", lock_area="casa"), {}).merges[0]
        assert m.keep_area == ()

    def test_web_device_without_area_pins_nothing(self):
        m = web_plan(self._registry(web_area=None), {}).merges[0]
        assert m.keep_area == ()

    def test_both_disabled_keeps_entities_as_they_are(self):
        """Casa's lock inside the GB entry: both devices disabled by the user."""
        entities = {e: EntityRow(e, disabled_by="device")
                    for e in ("switch.agency_8194", "switch.keypad_27191")}
        m = web_plan(self._registry(web_disabled=True, lock_disabled=True), entities).merges[0]
        assert m.disable_by_device == () and m.disable_by_user == ()

    def test_disabled_web_device_onto_enabled_lock_stays_off(self):
        entities = {"switch.agency_8194": EntityRow("switch.agency_8194", disabled_by="device")}
        m = web_plan(self._registry(web_disabled=True), entities).merges[0]
        assert m.disable_by_user == ("switch.agency_8194",)
        assert m.disable_by_device == ()

    def test_enabled_entities_onto_disabled_lock_follow_the_device(self):
        m = web_plan(self._registry(lock_disabled=True), {}).merges[0]
        assert m.disable_by_device == ("switch.agency_8194", "switch.keypad_27191")

    def test_user_disabled_entity_is_left_alone(self):
        entities = {"switch.agency_8194": EntityRow("switch.agency_8194", disabled_by="user")}
        m = web_plan(self._registry(lock_disabled=True), entities).merges[0]
        assert "switch.agency_8194" not in m.disable_by_device

    def test_done_registry_has_nothing_to_do(self):
        devices = [d for d in self._registry() if d.device_id != "web"]
        assert web_plan(devices, {}).is_empty

    def test_each_lock_merges_into_its_own_device(self):
        other = 17910279140
        devices = self._registry() + [
            DeviceRow("lock2", ids((DOMAIN, other)), entity_ids=("lock.casa",)),
            DeviceRow("web2", ids((DOMAIN, f"web_{other}")), via_device_id="lock2",
                      entity_ids=("switch.claudio",)),
        ]
        pairs = {(m.source_device_id, m.target_device_id) for m in web_plan(devices, {}).merges}
        assert pairs == {("web", "lock"), ("web2", "lock2")}

    def test_lone_web_device_becomes_the_lock_device(self):
        devices = [DeviceRow("web", ids((DOMAIN, WEB)), entity_ids=("switch.a",))]
        got = web_plan(devices, {})
        assert got.merges == ()
        assert got.renames[0].new_identifiers == ids((DOMAIN, LOCK_ID))

    def test_lock_identifier_matches_int_or_str(self):
        devices = [
            DeviceRow("lock", ids((DOMAIN, str(LOCK_ID)))),
            DeviceRow("web", ids((DOMAIN, WEB)), entity_ids=("switch.a",)),
        ]
        assert web_plan(devices, {}).merges[0].target_device_id == "lock"

    def test_legacy_web_id_then_merge(self):
        """Pre-0.5 install: identifier migration renames ("web_id", x) to
        (DOMAIN, "web_x"); the merge then folds it into the lock."""
        devices = [
            DeviceRow("lock", ids((DOMAIN, LOCK_ID))),
            DeviceRow("web", ids(("web_id", LOCK_ID)), via_device_id="lock",
                      entity_ids=("switch.a",)),
        ]
        rename = plan(devices).renames[0]
        after = [devices[0], DeviceRow("web", rename.new_identifiers, entity_ids=("switch.a",))]
        assert web_plan(after, {}).merges[0].target_device_id == "lock"
