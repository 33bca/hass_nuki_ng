"""The coordinator poll when Nuki Web (api.nuki.io) is down but the bridge works.

Runs `NukiCoordinator._update` without Home Assistant: the few HA modules
`nuki.py` imports are stubbed, and the coordinator is built without __init__.
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timezone

import pytest

import conftest


class HomeAssistantError(Exception):
    pass


class UpdateFailed(Exception):
    pass


def _stub(name, **attrs):
    module = sys.modules.get(name) or types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_nuki():
    try:
        import homeassistant  # noqa: F401  (real HA: nothing to stub)
    except ImportError:
        _stub("homeassistant")
        _stub("homeassistant.helpers")
        _stub("homeassistant.components")
        _stub("homeassistant.helpers.update_coordinator",
              DataUpdateCoordinator=object, UpdateFailed=UpdateFailed)
        _stub("homeassistant.helpers.event", async_call_later=lambda *a, **k: None)
        _stub("homeassistant.helpers.device_registry")
        _stub("homeassistant.helpers.network", get_url=lambda hass: "")
        _stub("homeassistant.components.webhook")
        _stub("homeassistant.exceptions", HomeAssistantError=HomeAssistantError)
    try:
        import requests  # noqa: F401
    except ImportError:
        _stub("requests", RequestException=Exception)
    return conftest._load("nuki")


nuki = _load_nuki()
HAError = nuki.HomeAssistantError

LOCK = {"nukiId": 0x1A2B, "deviceType": 0, "name": "Door", "lastKnownState": {"state": 1}}


class FakeApi:
    def __init__(self, web_up=True, auth_up=True):
        self.web_up = web_up
        self.auth_up = auth_up
        self.web_calls = 0

    def can_bridge(self):
        return True

    def can_web(self):
        return True

    async def bridge_check_callback(self, hook):
        return []

    async def bridge_info(self):
        return {"ids": {"hardwareId": 1}, "scanResults": []}

    async def bridge_list(self):
        return {LOCK["nukiId"]: dict(LOCK)}

    async def web_list(self):
        self.web_calls += 1
        if not self.web_up:
            raise HAError("Bridge request failed: ConnectTimeout")
        web_id = int("1a2b", 16)
        return {web_id: {"config": {"buttonEnabled": True}, "advancedConfig": {"autoLock": False}}}

    async def web_list_all_auths(self, web_id):
        self.web_calls += 1
        if not self.auth_up:
            raise HAError("timeout")
        return {7: {"id": 7, "name": "A"}}

    async def web_get_last_unlock_log(self, web_id):
        return {"name": "A"}

    async def web_get_last_log(self, web_id):
        return {"name": "A"}


def coordinator(api):
    coord = nuki.NukiCoordinator.__new__(nuki.NukiCoordinator)
    coord.api = api
    coord.data = None  # before the first successful poll
    coord.bridge_hook = "http://ha/hook"
    coord._web_failed_at = None
    return coord


def poll(coord):
    result = asyncio.run(coord._update())
    coord.data = result
    return result


def test_first_poll_succeeds_with_nuki_web_down():
    coord = coordinator(FakeApi(web_up=False))
    device = poll(coord)["devices"][LOCK["nukiId"]]
    assert device["lastKnownState"] == {"state": 1}
    assert device["web_auth"] == {}
    assert device["web_auth_ok"] is False
    assert coord._web_failed_at is not None


def test_auth_fetch_failing_at_first_poll_does_not_fail_setup():
    # Upstream fell back to self.data here, which is None at the first poll
    coord = coordinator(FakeApi(auth_up=False))
    device = poll(coord)["devices"][LOCK["nukiId"]]
    assert device["web_auth_ok"] is False
    assert device["config"] == {"buttonEnabled": True}


def test_outage_keeps_last_web_data_and_skips_web_until_retry():
    api = FakeApi()
    coord = coordinator(api)
    poll(coord)
    api.web_up = False
    poll(coord)  # fails, noted
    calls = api.web_calls
    device = poll(coord)["devices"][LOCK["nukiId"]]  # within WEB_RETRY: no Nuki Web call
    assert api.web_calls == calls
    assert device["web_auth"] == {7: {"id": 7, "name": "A"}}
    assert device["advancedConfig"] == {"autoLock": False}
    assert device["web_auth_ok"] is False


def test_web_back_after_retry():
    api = FakeApi(web_up=False)
    coord = coordinator(api)
    poll(coord)
    api.web_up = True
    coord._web_failed_at = datetime.now(timezone.utc) - nuki.WEB_RETRY
    device = poll(coord)["devices"][LOCK["nukiId"]]
    assert device["web_auth_ok"] is True
    assert device["config"] == {"buttonEnabled": True}
    assert coord._web_failed_at is None


def test_web_only_entry_still_fails_without_nuki_web():
    api = FakeApi(web_up=False)
    api.can_bridge = lambda: False
    coord = coordinator(api)
    with pytest.raises(Exception) as err:
        asyncio.run(coord._update())
    assert type(err.value).__name__ == "UpdateFailed"


def test_device_unknown_to_nuki_web_does_not_stall_the_others():
    # e.g. a Smart Door (bridge only) listed before a lock Nuki Web holds
    door = {"nukiId": 0x99, "deviceType": 3, "name": "Smart Door", "lastKnownState": {}}

    class TwoDevices(FakeApi):
        async def bridge_list(self):
            return {door["nukiId"]: dict(door), LOCK["nukiId"]: dict(LOCK)}

        async def web_list_all_auths(self, web_id):
            if web_id != int("1a2b", 16):
                raise HAError("404")
            return await super().web_list_all_auths(web_id)

    coord = coordinator(TwoDevices())
    devices = poll(coord)["devices"]
    assert devices[LOCK["nukiId"]]["web_auth_ok"] is True
    assert devices[LOCK["nukiId"]]["web_auth"] == {7: {"id": 7, "name": "A"}}
    assert devices[door["nukiId"]]["web_auth_ok"] is False
    assert coord._web_failed_at is None


def test_per_device_failure_stays_with_that_device():
    coord = coordinator(FakeApi(auth_up=False))
    poll(coord)
    assert coord._web_failed_at is None  # Nuki Web itself answered
