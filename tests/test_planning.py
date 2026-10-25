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
        "authId": 8199,
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
        assert attrs["Auth ID"] == 8199
        assert attrs["Type"] == "keypad code"
        assert attrs["Fingerprints"] == 1

    def test_unknown_type_passes_through(self):
        assert planning.auth_attributes({"type": 99})["Type"] == 99

    def test_object_id_ends_with_auth_id(self):
        assert planning.auth_object_id("Door", self.AUTH, "abc").endswith(" 8199")

    def test_object_id_falls_back_to_entry_id(self):
        assert planning.auth_object_id("Door", {"name": "X"}, "abc").endswith(" abc")


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
