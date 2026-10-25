from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import service
from homeassistant.helpers.entity import EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.helpers import device_registry as dr

from .nuki import NukiCoordinator
from .constants import DOMAIN, PLATFORMS
from .registry_migration import async_migrate_device_registry


def via_device_id(entity, identifier: tuple[str, str]) -> str | None:
    """Return the device registry id of this config entry's device with this identifier.

    Replaces the `via_device` identifier tuple, deprecated in HA 2026.10 and removed in
    2027.8. Uses async_get_device_by_identifier (scoped to the entity's config entry):
    async_get_device is deprecated in the same release. None when the parent is not
    registered yet (HA ignored an unknown `via_device` the same way); the link is then
    made on the next start.
    """
    if entity.hass is None or entity.platform is None or entity.platform.config_entry is None:
        return None
    device = dr.async_get(entity.hass).async_get_device_by_identifier(
        identifier, entity.platform.config_entry.entry_id
    )
    return device.id if device else None

OPENER_TYPE = 1
LOCK_TYPE = 0

_LOGGER = logging.getLogger(__name__)


# ------------------------------------------------------
#  Home Assistant Setup
# ------------------------------------------------------

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    # Options (set via "Configure") override the values from the initial setup
    data = {**entry.data, **entry.options}
    # Hashed bridge auth is opt-in via the options only. Entries created by
    # older releases may carry use_hashed=True in their data, which upstream
    # ignored since 2022; honouring it now would silently change their auth.
    data["use_hashed"] = entry.options.get("use_hashed", False)
    _LOGGER.debug(f"async_setup_entry: {entry.entry_id}, bridge: {data.get('address')}, hashed token: {data.get('use_hashed', False)}")

    # Convert devices still registered under the pre-0.5.x identifier domains
    # before any platform re-creates them. No-op once converted.
    await async_migrate_device_registry(hass, entry)

    coordinator = NukiCoordinator(hass, entry, data)
    entry.runtime_data = coordinator

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device
) -> bool:
    """Allow removing a device from the UI when it no longer has entities.

    Without this, Home Assistant refuses every deletion with "Config entry does
    not support device removal", which leaves users unable to clear out rows
    left behind by earlier identifier schemes.
    """
    from homeassistant.helpers import entity_registry as er

    remaining = er.async_entries_for_device(
        er.async_get(hass), device.id, include_disabled_entities=True
    )
    if remaining:
        _LOGGER.debug(
            "Refusing to remove device %s: still has %d entities",
            device.id,
            len(remaining),
        )
        return False
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry):
    coordinator = entry.runtime_data
    await coordinator.unload()
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    entry.runtime_data = None
    return True


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _targeted_nuki_ids(hass: HomeAssistant, call) -> set[str]:
    """Nuki device ids (lock/opener) named by the call's device and entity targets.

    The Web API device ("web_<id>") counts as its lock. The bridge and other
    devices map to nothing.
    """
    from homeassistant.helpers import entity_registry as er

    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    device_ids = set(_as_list(call.data.get("device_id")))
    for entity_id in _as_list(call.data.get("entity_id")):
        if (ent := ent_reg.async_get(entity_id)) and ent.device_id:
            device_ids.add(ent.device_id)
    result: set[str] = set()
    for device_id in device_ids:
        if not (device := dev_reg.async_get(device_id)):
            continue
        for domain, value in device.identifiers:
            if domain != DOMAIN:
                continue
            value = str(value)
            result.add(value[len("web_"):] if value.startswith("web_") else value)
    return result


def _register_coordinator_service(hass: HomeAssistant, name: str, handler):
    async def handler_(call):
        # HA 2026.10 removed the `hass` argument of async_extract_config_entry_ids.
        for entry_id in await service.async_extract_config_entry_ids(call):
            if entry := hass.config_entries.async_get_entry(entry_id):
                if entry.domain == DOMAIN and entry.runtime_data is not None:
                    _LOGGER.debug(f"service call: {name} for {entry.domain}")
                    await handler(entry.runtime_data, call)

    hass.services.async_register(DOMAIN, name, handler_)


async def _execute_action(hass: HomeAssistant, coordinator, call):
    """Run the action on the targeted locks/openers only, never on the whole entry.

    Upstream sent it to every device of the entry, so e.g. `deactivate_rto`
    aimed at an Opener reached a Smart Lock as action 2 ("lock").
    """
    targeted = _targeted_nuki_ids(hass, call)
    known = {str(dev_id): dev_id for dev_id in coordinator.data.get("devices", {})}
    selected = [known[t] for t in targeted if t in known]
    if not selected:
        raise ServiceValidationError(
            "execute_action needs a Nuki lock or opener device (or one of its entities) as target"
        )
    await coordinator.action_for_devices(call.data.get("action"), selected)


async def async_setup(hass: HomeAssistant, config) -> bool:
    _register_coordinator_service(
        hass,
        "bridge_reboot",
        lambda coord, _: coord.do_reboot(),
    )
    _register_coordinator_service(
        hass,
        "bridge_fwupdate",
        lambda coord, _: coord.do_fwupdate(),
    )
    _register_coordinator_service(
        hass,
        "bridge_delete_callback",
        lambda coord, call: coord.do_delete_callback(call.data.get("callback")),
    )
    _register_coordinator_service(
        hass,
        "execute_action",
        lambda coord, call: _execute_action(hass, coord, call),
    )

    return True


# ------------------------------------------------------
#  Nuki Base Entities
# ------------------------------------------------------

class NukiEntity(CoordinatorEntity):
    """Base entity for Nuki locks and openers."""

    def __init__(self, coordinator, device_id: str):
        super().__init__(coordinator)
        self.device_id = device_id

    # ---- ID + Name helpers -------------------------------------

    def set_id(self, prefix: str, suffix: str):
        self.id_prefix = prefix
        self.id_suffix = suffix

    def set_name(self, name: str):
        self._attr_name_suffix = name

    @property
    def name_suffix(self):
        return self._attr_name_suffix

    @property
    def get_name(self):
        return "Nuki %s" % (self.data.get("name", self.device_id))

    @property
    def name(self) -> str:
        return "%s %s" % (self.get_name, self.name_suffix)

    @property
    def unique_id(self) -> str:
        return "nuki-%s-%s" % (self.device_id, self.id_suffix)

    # ---- Data Access --------------------------------------------

    @property
    def available(self):
        if "nukiId" not in self.data:
            return False
        return super().available

    @property
    def data(self) -> dict:
        return self.coordinator.device_data(self.device_id)

    @property
    def last_state(self) -> dict:
        return self.data.get("lastKnownState", {})

    @property
    def model(self) -> str:
        if self.coordinator.is_lock(self.device_id):
            return "Nuki Smart Lock"
        if self.coordinator.is_opener(self.device_id):
            return "Nuki Opener"
        return "Nuki Device"

    # ---- FIXED device_info --------------------------------------

    @property
    def device_info(self):
        """
        Correct HA-compatible device definition.
        Ensures:
        - identifiers use (DOMAIN, id)
        - via_device only set if bridge_id exists
        """
        # Bridge Hardware-ID (may be None)
        bridge_id = self.coordinator.info_data().get("ids", {}).get("hardwareId")

        info = {
            "identifiers": {(DOMAIN, self.device_id)},
            "name": self.get_name,
            "manufacturer": "Nuki",
            "model": self.model,
            "sw_version": self.data.get("firmwareVersion"),
        }

        # Add bridging only when valid. HA 2026.10 deprecated `via_device` (an identifier
        # tuple; removed in 2027.8) for `via_device_id` (the parent's device registry id).
        if bridge_id and (via := via_device_id(self, (DOMAIN, bridge_id))):
            info["via_device_id"] = via

        return info


# ------------------------------------------------------
#  Nuki Bridge Entity
# ------------------------------------------------------

class NukiBridge(CoordinatorEntity):
    """Represents the Nuki Bridge device."""

    def set_id(self, suffix: str):
        self.id_suffix = suffix

    def set_name(self, name: str):
        self.name_suffix = name

    @property
    def name(self) -> str:
        return "Nuki Bridge %s" % (self.name_suffix)

    @property
    def unique_id(self) -> str:
        return "nuki-bridge-%s-%s" % (self.get_id, self.id_suffix)

    @property
    def data(self) -> dict:
        return self.coordinator.data.get("bridge_info", {})

    @property
    def get_id(self):
        return self.data.get("ids", {}).get("hardwareId")

    @property
    def device_info(self):
        """Correct HA-compliant Bridge info."""
        model = (
            "Hardware Bridge"
            if self.data.get("bridgeType", 1) == 1
            else "Software Bridge"
        )
        versions = self.data.get("versions", {})

        return {
            "identifiers": {(DOMAIN, self.get_id)},
            "name": "Nuki Bridge",
            "manufacturer": "Nuki",
            "model": model,
            "sw_version": versions.get("firmwareVersion"),
        }


# ------------------------------------------------------
#  Advanced Opener Entity
# ------------------------------------------------------

class NukiOpenerRingSuppressionEntity(NukiEntity):

    SUP_RING = 4
    SUP_RTO = 2
    SUP_CM = 1

    @property
    def entity_category(self):
        return EntityCategory.CONFIG

    @property
    def doorbellSuppression(self):
        return self.coordinator.info_field(
            self.device_id, 0, "openerAdvancedConfig", "doorbellSuppression"
        )

    async def update_doorbell_suppression(self, new_value):
        await self.coordinator.update_config(
            self.device_id,
            "openerAdvancedConfig",
            dict(doorbellSuppression=new_value),
        )
