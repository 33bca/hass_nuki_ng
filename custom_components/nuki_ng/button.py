from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.helpers.entity import EntityCategory

import logging

from . import NukiBridge, NukiEntity
from .constants import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    entities = []
    coordinator = entry.runtime_data

    if coordinator.api.can_bridge():
        entities.append(NukiBridgeRestartButton(coordinator))
        entities.append(NukiBridgeFWUpdateButton(coordinator))
    if coordinator.api.can_web():
        for dev_id in coordinator.data.get("devices", {}):
            entities.append(NukiSyncButton(coordinator, dev_id))
    async_add_entities(entities)
    return True

class NukiBridgeRestartButton(NukiBridge, ButtonEntity):
    """Defines a Bridge restart button."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self.set_id("reboot")
        self.set_name("Reboot")
        self._attr_device_class = ButtonDeviceClass.RESTART
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self.coordinator.do_reboot()

class NukiBridgeFWUpdateButton(NukiBridge, ButtonEntity):
    """Defines a Bridge update button."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self.set_id("fw_update")
        self.set_name("Firmware Update")
        self._attr_device_class = ButtonDeviceClass.UPDATE
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self.coordinator.do_fwupdate()


class NukiSyncButton(NukiEntity, ButtonEntity):
    """Forces a state sync from the physical lock via the Web API."""

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id)
        self.set_id("button", "sync")
        self.set_name("Sync")
        self._attr_icon = "mdi:sync"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self.coordinator.do_sync(self.device_id)
