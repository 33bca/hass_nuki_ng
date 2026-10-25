from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.core import callback

import logging

from . import NukiEntity, NukiOpenerRingSuppressionEntity
from .planning import AUTH_ICONS, auth_attributes, auth_object_id, removed_auths
from .states import LockModes

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass,
    entry,
    async_add_entities
):
    coordinator = entry.runtime_data
    known_devices = set()
    auth_entities = {}

    @callback
    def _add_new():
        new = []
        devices = coordinator.data.get("devices", {})
        # Entries deleted in Nuki: release their switches. They then show as
        # "no longer provided" and can be deleted from the UI; the registry
        # (and so the entity id) is left alone in case the entry comes back.
        gone = removed_auths(
            set(auth_entities),
            {dev_id: coordinator.device_data(dev_id).get("web_auth", {}) for dev_id in devices},
            {dev_id: coordinator.device_data(dev_id).get("web_auth_ok", False) for dev_id in devices},
        )
        for key in gone:
            entity = auth_entities.pop(key)
            if entity.hass is None:
                # Disabled in the registry (never added) or not added yet
                continue
            _LOGGER.info(f"Authorization {key[1]} no longer exists in Nuki, removing {entity.entity_id}")
            hass.async_create_task(entity.async_remove())
        for dev_id in devices:
            # New auth entries (tracked per (dev_id, auth_id) pair)
            for auth_id in coordinator.device_data(dev_id).get("web_auth", {}):
                if (dev_id, auth_id) not in auth_entities:
                    entity = AuthEntry(coordinator, dev_id, auth_id)
                    auth_entities[(dev_id, auth_id)] = entity
                    new.append(entity)

            # Device-level switches — added once per new device
            if dev_id not in known_devices:
                known_devices.add(dev_id)
                if coordinator.info_field(dev_id, None, "advancedConfig", "autoLock") is not None:
                    new.append(LockAutoLock(coordinator, dev_id))
                if coordinator.info_field(dev_id, None, "config", "buttonEnabled") is not None:
                    new.append(LockButtonEnabled(coordinator, dev_id))
                if coordinator.info_field(dev_id, -1, "openerAdvancedConfig", "doorbellSuppression") >= 0:
                    new.append(OpenerRingSuppression(coordinator, dev_id))
                    new.append(OpenerRingSuppressionRTO(coordinator, dev_id))
                    new.append(OpenerRingSuppressionCM(coordinator, dev_id))
                if coordinator.is_opener(dev_id):
                    new.append(OpenerContinuousMode(coordinator, dev_id))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))
    return True


class AuthEntry(NukiEntity, SwitchEntity):

    def __init__(self, coordinator, device_id, auth_id):
        super().__init__(coordinator, device_id)
        self.auth_id = auth_id
        self.set_id("switch", f"{auth_id}_auth_entry")

    @property
    def name(self) -> str:
        # On the lock device (one device per lock since 0.6.3); Home Assistant
        # prefixes the device name. The name follows the entry's
        # current name in the Nuki app / Nuki Web; a name set in Home Assistant
        # always wins. Entity ids never change on a rename.
        return self.auth_data.get("name") or "undefined"

    @property
    def suggested_object_id(self) -> str | None:
        return auth_object_id(self.auth_data, self.auth_id)

    @property
    def auth_data(self):
        return self.data.get("web_auth", {}).get(self.auth_id, {})

    @property
    def is_on(self):
        return self.auth_data.get("enabled") == True

    @property
    def icon(self):
        return AUTH_ICONS.get(self.auth_data.get("type", -1), "mdi:account-question")

    @property
    def available(self):
        if "id" not in self.auth_data:
            return False
        return super().available

    async def async_turn_on(self, **kwargs):
        await self.coordinator.update_web_auth(self.device_id, self.auth_data, dict(enabled=True))

    async def async_turn_off(self, **kwargs):
        await self.coordinator.update_web_auth(self.device_id, self.auth_data, dict(enabled=False))

    @property
    def extra_state_attributes(self):
        return auth_attributes(self.auth_data)

    @property
    def entity_category(self):
        return EntityCategory.CONFIG

class LockAutoLock(NukiEntity, SwitchEntity):

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self.set_id("switch", "auto_lock")
        self.set_name("Auto lock")
        self._attr_icon = "mdi:lock-clock"

    @property
    def is_on(self):
        return self.coordinator.info_field(self.device_id, False, "advancedConfig", "autoLock")

    @property
    def entity_category(self):
        return EntityCategory.CONFIG

    async def async_turn_on(self, **kwargs):
        await self.coordinator.update_config(self.device_id, "advancedConfig", dict(autoLock=True))

    async def async_turn_off(self, **kwargs):
        await self.coordinator.update_config(self.device_id, "advancedConfig", dict(autoLock=False))

class LockButtonEnabled(NukiEntity, SwitchEntity):
    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self.set_id("switch", "button_enabled")
        self.set_name("Button Enabled")
        self._attr_icon = "mdi:lock-clock"

    @property
    def is_on(self):
        return self.coordinator.info_field(
            self.device_id, False, "config", "buttonEnabled"
        )

    @property
    def entity_category(self):
        return EntityCategory.CONFIG

    async def async_turn_on(self, **kwargs):
        await self.coordinator.update_config(
            self.device_id, "config", dict(buttonEnabled=True)
        )

    async def async_turn_off(self, **kwargs):
        await self.coordinator.update_config(
            self.device_id, "config", dict(buttonEnabled=False)
        )

class OpenerRingSuppressionSwitch(NukiOpenerRingSuppressionEntity, SwitchEntity):

    def __init__(self, coordinator, device_id, suppression):
        super().__init__(coordinator, device_id)
        self._suppression = suppression

    @property
    def entity_registry_enabled_default(self):
        return False

    @property
    def is_on(self):
        return (self.doorbellSuppression & self._suppression) != 0

    async def async_turn_on(self, **kwargs):
        await self.update_doorbell_suppression(self.doorbellSuppression | self._suppression)

    async def async_turn_off(self, **kwargs):
        await self.update_doorbell_suppression(self.doorbellSuppression & (~self._suppression))


class OpenerRingSuppression(OpenerRingSuppressionSwitch):

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id, NukiOpenerRingSuppressionEntity.SUP_RING)
        self.set_id("switch", "ring_suppression")
        self.set_name("Ring suppression")
        self._attr_icon = "mdi:bell-cancel"


class OpenerRingSuppressionRTO(OpenerRingSuppressionSwitch):

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id, NukiOpenerRingSuppressionEntity.SUP_RTO)
        self.set_id("switch", "ring_suppression_rto")
        self.set_name("Ring suppression (Ring to Open)")
        self._attr_icon = "mdi:bell-cancel"


class OpenerRingSuppressionCM(OpenerRingSuppressionSwitch):

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id, NukiOpenerRingSuppressionEntity.SUP_CM)
        self.set_id("switch", "ring_suppression_cm")
        self.set_name("Ring suppression (Continuous Mode)")
        self._attr_icon = "mdi:bell-cancel"


class OpenerContinuousMode(NukiEntity, SwitchEntity):

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self.set_id("switch", "continuous_mode")
        self.set_name("Continuous Mode")

    @property
    def icon(self) -> str | None:
        return "mdi:lock-open-check" if self.is_on else "mdi:lock-check"

    @property
    def is_on(self):
        return LockModes(self.last_state.get("mode", LockModes.DOOR_MODE.value)) == LockModes.CONTINUOUS_MODE

    @property
    def entity_category(self):
        return EntityCategory.CONFIG

    async def async_turn_on(self, **kwargs):
        await self.coordinator.action(self.device_id, "activate_continuous_mode")

    async def async_turn_off(self, **kwargs):
        await self.coordinator.action(self.device_id, "deactivate_continuous_mode")
