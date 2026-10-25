"""Tests for the pure helpers in planning.py (no Home Assistant needed)."""

from __future__ import annotations

from conftest import planning

HOOK = "http://ha.example:8123/api/webhook/nuki_ng_bridge_hook_x"
OTHER = "http://other.example/cb"


def cb(*urls):
    return [{"id": i, "url": u} for i, u in enumerate(urls)]


class TestCallbackPlan:
    def test_ours_once_in_any_slot_is_left_alone(self):
        plan = planning.plan_callback_changes(cb(OTHER, HOOK), HOOK)
        assert plan == dict(remove_ids=[], add=False, full=False)

    def test_duplicates_removed_highest_id_first(self):
        plan = planning.plan_callback_changes(cb(HOOK, HOOK, HOOK), HOOK)
        assert plan["remove_ids"] == [2, 1]
        assert plan["add"] is False

    def test_missing_is_added(self):
        plan = planning.plan_callback_changes(cb(OTHER), HOOK)
        assert plan == dict(remove_ids=[], add=True, full=False)

    def test_full_slots_of_others_are_never_evicted(self):
        plan = planning.plan_callback_changes(cb(OTHER, OTHER + "2", OTHER + "3"), HOOK)
        assert plan == dict(remove_ids=[], add=True, full=True)

    def test_empty_list(self):
        assert planning.plan_callback_changes([], HOOK)["add"] is True


class TestAuthAttributes:
    AUTH = {
        "id": "abc",
        "authId": 4242,
        "type": 13,
        "name": "Guest",
        "enabled": True,
        "code": 123456,
        "fingerprints": {"f1": "x"},
        "remoteAllowed": False,
        "lockCount": 3,
        "lastActiveDate": "2026-10-01T00:00:00Z",
    }

    def test_pin_never_exposed(self):
        attrs = planning.auth_attributes(self.AUTH)
        assert "code" not in {k.lower() for k in attrs}
        assert 123456 not in attrs.values()

    def test_identity_attributes(self):
        attrs = planning.auth_attributes(self.AUTH)
        assert attrs["Nuki name"] == "Guest"
        assert attrs["Auth ID"] == 4242
        assert attrs["Type"] == "keypad code"
        assert attrs["Fingerprints"] == 1

    def test_unknown_type_passes_through(self):
        assert planning.auth_attributes({"type": 99})["Type"] == 99

    def test_object_id_ends_with_auth_id(self):
        assert planning.auth_object_id(self.AUTH, "abc").endswith(" 4242")

    def test_object_id_falls_back_to_entry_id(self):
        assert planning.auth_object_id({"name": "X"}, "abc").endswith(" abc")


class TestRemovedAuths:
    def test_removed_entry_detected(self):
        gone = planning.removed_auths({(1, "a"), (1, "b")}, {1: {"a": {}}}, {1: True})
        assert gone == {(1, "b")}

    def test_failed_fetch_never_removes(self):
        assert planning.removed_auths({(1, "a")}, {1: {"b": {}}}, {1: False}) == set()

    def test_empty_list_is_treated_as_outage(self):
        assert planning.removed_auths({(1, "a")}, {1: {}}, {1: True}) == set()

    def test_unknown_device_is_skipped(self):
        assert planning.removed_auths({(2, "a")}, {1: {"x": {}}}, {1: True}) == set()


class TestActionMismatches:
    def test_lock_action_on_lock(self):
        assert planning.action_mismatches("unlock", {1: "lock"}) == []

    def test_opener_action_never_reaches_a_lock(self):
        """activate_rto shares code 1 with unlock."""
        assert planning.action_mismatches("activate_rto", {1: "lock", 2: "opener"}) == [1]

    def test_lock_action_never_reaches_an_opener(self):
        assert planning.action_mismatches("open", {2: "opener"}) == [2]

    def test_unknown_action_matches_nothing(self):
        assert planning.action_mismatches("bogus", {1: "lock"}) == [1]

    def test_unknown_device_kind_is_refused(self):
        assert planning.action_mismatches("lock", {3: "other"}) == [3]


class TestDevicesToSync:
    def test_disabled_device_is_skipped(self):
        assert planning.devices_to_sync([1001, 1002], {1002}) == [1001]

    def test_all_enabled(self):
        assert planning.devices_to_sync([1, 2], set()) == [1, 2]

    def test_no_devices(self):
        assert planning.devices_to_sync([], {1}) == []


class TestCarryWebData:
    PREVIOUS = {
        "nukiId": 1,
        "config": {"buttonEnabled": True},
        "advancedConfig": {"autoLock": False},
        "web_auth": {7: {"id": 7, "name": "A"}},
        "last_log": {"name": "A"},
    }

    def test_missing_fields_come_from_the_last_good_poll(self):
        item = {"nukiId": 1}
        planning.carry_web_data(item, self.PREVIOUS)
        assert item["config"] == {"buttonEnabled": True}
        assert item["advancedConfig"] == {"autoLock": False}
        assert item["web_auth"] == {7: {"id": 7, "name": "A"}}
        assert item["last_log"] == {"name": "A"}
        assert item["last_unlock_log"] == {}
        assert item["web_auth_ok"] is False

    def test_fresh_fields_are_kept(self):
        item = {"nukiId": 1, "config": {"buttonEnabled": False}}
        planning.carry_web_data(item, self.PREVIOUS)
        assert item["config"] == {"buttonEnabled": False}

    def test_no_previous_poll(self):
        item = {"nukiId": 1}
        planning.carry_web_data(item, {})
        assert item["web_auth"] == {}
        assert "config" not in item
        assert item["web_auth_ok"] is False


class TestPlanReconfigure:
    DATA = {"address": "old.lan", "token": "t1", "web_token": "w1", "hass_url": "http://ha:8123", "update_seconds": 30}

    def test_new_address_only(self):
        updates, options = planning.plan_reconfigure(
            self.DATA, {"update_seconds": 20}, {"address": "new.lan", "token": "", "web_token": ""}
        )
        assert updates == {"address": "new.lan"}
        assert options == {"update_seconds": 20}

    def test_blank_fields_keep_the_current_values(self):
        updates, _ = planning.plan_reconfigure(self.DATA, {}, {"address": "", "hass_url": "", "token": "", "web_token": ""})
        assert updates == {}

    def test_new_token_replaces_one_set_in_the_options(self):
        updates, options = planning.plan_reconfigure(
            self.DATA, {"token": "t2", "use_hashed": True}, {"token": "t3"}
        )
        assert updates == {"token": "t3"}
        # Otherwise the options token would still win at setup
        assert options == {"use_hashed": True}

    def test_unchanged_values_are_no_updates(self):
        updates, _ = planning.plan_reconfigure(self.DATA, {}, {"address": "old.lan", "web_token": "w1"})
        assert updates == {}

    def test_effective_config(self):
        updates, options = planning.plan_reconfigure(self.DATA, {"token": "t2"}, {"address": "new.lan"})
        assert planning.effective_config(self.DATA, updates, options)["address"] == "new.lan"
        assert planning.effective_config(self.DATA, updates, options)["token"] == "t2"


class TestSameBridge:
    def test_same_hardware_id(self):
        assert planning.is_same_bridge({1}, 1) is True

    def test_other_bridge(self):
        assert planning.is_same_bridge({1, "12345"}, 2) is False

    def test_unknown_before(self):
        # Web-only entries or entries whose bridge never answered: nothing to compare
        assert planning.is_same_bridge(set(), 2) is True

    def test_new_bridge_reports_no_id(self):
        assert planning.is_same_bridge({"1"}, None) is False


class TestWebRetry:
    def test_web_is_asked_when_never_failed(self):
        from datetime import datetime, timezone
        assert planning.web_due(None, datetime.now(timezone.utc)) is True

    def test_web_waits_after_a_failure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        assert planning.web_due(now, now + planning.WEB_RETRY / 2) is False
        assert planning.web_due(now, now + planning.WEB_RETRY) is True
