from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.core import callback

import logging
from datetime import datetime

from . import NukiEntity, NukiBridge
from .constants import DOMAIN
from .states import DoorSensorStates, LockStates, DoorSecurityStates

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    known = set()

    if coordinator.api.can_bridge():
        async_add_entities([
            BridgeWifiVersion(coordinator),
            BridgeVersion(coordinator),
        ])

    @callback
    def _add_new():
        new = []
        for dev_id in coordinator.data.get("devices", {}):
            if dev_id not in known:
                known.add(dev_id)
                new.append(LockState(coordinator, dev_id))
                if coordinator.api.can_bridge():
                    new.append(RSSI(coordinator, dev_id))
                new.append(LockVersion(coordinator, dev_id))
                if coordinator.device_supports(dev_id, "batteryChargeState"):
                    new.append(Battery(coordinator, dev_id))
                if coordinator.device_supports(dev_id, "doorsensorStateName"):
                    new.append(DoorSensorState(coordinator, dev_id))
                    new.append(DoorSecurityState(coordinator, dev_id))
                # Read from the Nuki Web activity log: added for every device
                # when the Web API is configured. Upstream added them only if
                # the log already had a matching entry at the first poll, so
                # some locks never got them.
                if coordinator.api.can_web():
                    new.append(LastLog(coordinator, dev_id))
                    new.append(LastUnlockUser(coordinator, dev_id))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))
    return True


class Battery(NukiEntity, SensorEntity):
    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self.set_id("sensor", "battery")
        self.set_name("Battery")
        self._attr_device_class = "battery"
        self._attr_state_class = "measurement"

    @property
    def native_unit_of_measurement(self):
        return "%"

    @property
    def native_value(self):
        return self.last_state.get("batteryChargeState", 0)

    @property
    def state(self):
        return self.native_value

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC


class LockState(NukiEntity, SensorEntity):
    _attr_translation_key = "state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [state.translation_key for state in LockStates]

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self.set_id("sensor", "state")
        self.set_name("State")
        self._attr_icon = "mdi:door"

    @property
    def native_value(self):
        state_name = self.last_state.get("stateName")
        if state_name is None:
            return None
        if state_name == "unlocked (lock 'n' go)":
            return LockStates.LOCK_N_GO.translation_key
        return state_name.lower().replace(" ", "_")

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC


class RSSI(NukiEntity, SensorEntity):
    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self.set_id("sensor", "rssi")
        self.set_name("RSSI")
        self._attr_device_class = "signal_strength"
        self._attr_state_class = "measurement"

    @property
    def native_unit_of_measurement(self):
        return "dBm"

    @property
    def native_value(self):
        return self.data.get("bridge_info", {}).get("rssi")

    @property
    def state(self):
        return self.native_value

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC


class DoorSensorState(NukiEntity, SensorEntity):
    _attr_translation_key = "door_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [state.translation_key for state in DoorSensorStates]

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self.set_id("sensor", "door_state")
        self.set_name("Door State")
        self._attr_icon = "mdi:door"

    @property
    def native_value(self):
        state_name = self.last_state.get("doorsensorStateName")
        if state_name is None:
            return None
        if state_name == "door state unknown":
            return DoorSensorStates.DOOR_UNKNOWN.translation_key
        return state_name.lower().replace(" ", "_")

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC


class DoorSecurityState(NukiEntity, SensorEntity):
    _attr_translation_key = "door_security_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [state.translation_key for state in DoorSecurityStates]

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self.set_id("sensor", "door_security_state")
        self.set_name("Door Security State")
        self._attr_icon = "mdi:door-closed-lock"

    @property
    def icon(self):

        state = self.get_state()

        if state == DoorSecurityStates.CLOSED_AND_LOCKED:
            return "mdi:door-closed-lock"
        elif state == DoorSecurityStates.CLOSED_AND_UNLOCKED:
            return "mdi:door-closed"
        return "mdi:door-open"

    @property
    def native_value(self):
        return self.get_state().translation_key

    def get_state(self) -> DoorSecurityStates:
        lock_state = LockStates(self.last_state.get("state", LockStates.UNDEFINED.value))
        door_sensor_state = DoorSensorStates(
            self.last_state.get("doorsensorState", DoorSensorStates.UNKNOWN.value))

        if lock_state == LockStates.LOCKED and door_sensor_state == DoorSensorStates.DOOR_CLOSED:
            return DoorSecurityStates.CLOSED_AND_LOCKED
        elif door_sensor_state == DoorSensorStates.DOOR_CLOSED:
            return DoorSecurityStates.CLOSED_AND_UNLOCKED
        return DoorSecurityStates.OPEN


class BridgeWifiVersion(NukiBridge, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self.set_id("wifi_version")
        self.set_name("WiFi Firmware Version")

    @property
    def state(self):
        versions = self.data.get("versions", {})
        return versions.get("wifiFirmwareVersion")

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC


class BridgeVersion(NukiBridge, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self.set_id("version")
        self.set_name("Firmware Version")

    @property
    def state(self):
        versions = self.data.get("versions", {})
        return versions.get("firmwareVersion")

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC


class LockVersion(NukiEntity, SensorEntity):

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self.set_id("sensor", "version")
        self.set_name("Firmware Version")

    @property
    def state(self):
        return self.data.get("firmwareVersion")

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC

class LastLog(NukiEntity, SensorEntity):

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self.set_id("sensor", "last_log")
        self.set_name("Last Log")
        self._attr_icon = "mdi:history"

    @property
    def state(self):
        return self.coordinator.info_field(self.device_id, "Unknown", "last_log", "name")

    @property
    def extra_state_attributes(self):
        timestamp = self.coordinator.info_field(self.device_id, None, "last_log", "timestamp")
        action = self.coordinator.info_field(self.device_id, "unknown", "last_log", "action")
        return {
            "timestamp": datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else None,
            "action": action,
        }

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC

class LastUnlockUser(NukiEntity, SensorEntity):

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self.set_id("sensor", "last_unlock_user")
        self.set_name("Last Unlock user")
        self._attr_icon = "mdi:account-lock-open"

    @property
    def state(self):
        return self.coordinator.info_field(self.device_id, "Unknown", "last_unlock_log", "name")

    @property
    def extra_state_attributes(self):
        timestamp = self.coordinator.info_field(self.device_id, None, "last_unlock_log", "timestamp")
        action = self.coordinator.info_field(self.device_id, "unknown", "last_unlock_log", "action")
        return {
            "timestamp": datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else None,
            "action": action,
        }

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC
