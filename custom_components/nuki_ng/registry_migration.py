"""One-time device registry migration to consistent identifiers.

Early versions registered devices under the identifier domains ``id`` (lock,
bridge) and ``web_id`` (Nuki Web API) instead of the integration ``DOMAIN``.
The lock and bridge were later corrected to ``(DOMAIN, id)``, but no migration
shipped with that change, so existing installations ended up with *both* rows:
an empty ``("id", x)`` device next to the populated ``(DOMAIN, x)`` one. The
Web API device was never converted at all and still points its ``via_device``
at the stale ``("id", x)`` entry, which is what keeps that entry alive.

The planning half of this module is deliberately free of Home Assistant
imports: deciding what to rename and what to merge is a data-structure problem
and is unit-tested as one. ``async_migrate_device_registry`` is the thin part
that reads the registry, asks for a plan and applies it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .constants import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Identifier domains written by older releases, mapped to how the same device
# is addressed today.
LEGACY_LOCK_DOMAIN = "id"
LEGACY_WEB_DOMAIN = "web_id"

Identifier = tuple[str, object]


def migrate_identifier(identifier: Identifier) -> Identifier:
    """Return the current-scheme identifier for a possibly legacy one."""
    domain, value = identifier
    if domain == LEGACY_LOCK_DOMAIN:
        return (DOMAIN, value)
    if domain == LEGACY_WEB_DOMAIN:
        # The Web API device shares its numeric id with the lock, so it needs a
        # prefix to stay distinct once both live in the same domain.
        return (DOMAIN, f"web_{value}")
    return identifier


def is_legacy(identifier: Identifier) -> bool:
    return identifier[0] in (LEGACY_LOCK_DOMAIN, LEGACY_WEB_DOMAIN)


@dataclass(frozen=True)
class DeviceRow:
    """The parts of a device registry entry this migration cares about."""

    device_id: str
    identifiers: frozenset[Identifier]
    via_device_id: str | None = None
    entity_ids: tuple[str, ...] = ()
    area_id: str | None = None
    disabled: bool = False


@dataclass(frozen=True)
class Rename:
    """No device holds the new identifiers yet — rewrite them in place."""

    device_id: str
    new_identifiers: frozenset[Identifier]


@dataclass(frozen=True)
class Merge:
    """A device already holds the new identifiers — fold the legacy row into it.

    Renaming would raise, because the registry rejects duplicate identifiers.
    """

    source_device_id: str
    target_device_id: str
    move_entity_ids: tuple[str, ...] = ()
    repoint_device_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MigrationPlan:
    renames: tuple[Rename, ...] = field(default_factory=tuple)
    merges: tuple[Merge, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not self.renames and not self.merges


def plan_identifier_migration(devices: list[DeviceRow]) -> MigrationPlan:
    """Work out how to bring `devices` onto the current identifier scheme.

    Returns an empty plan when there is nothing legacy left, which makes the
    migration safe to run on every startup.
    """
    owner_of: dict[Identifier, str] = {}
    for device in devices:
        for identifier in device.identifiers:
            owner_of[identifier] = device.device_id

    children_of: dict[str, list[str]] = {}
    for device in devices:
        if device.via_device_id:
            children_of.setdefault(device.via_device_id, []).append(device.device_id)

    renames: list[Rename] = []
    merges: list[Merge] = []

    for device in devices:
        legacy = {i for i in device.identifiers if is_legacy(i)}
        if not legacy:
            continue

        new_identifiers = frozenset(migrate_identifier(i) for i in device.identifiers)

        # Does some *other* device already answer to any of the new identifiers?
        target_id = next(
            (
                owner
                for i in new_identifiers
                if (owner := owner_of.get(i)) and owner != device.device_id
            ),
            None,
        )

        if target_id is None:
            renames.append(
                Rename(device_id=device.device_id, new_identifiers=new_identifiers)
            )
            continue

        merges.append(
            Merge(
                source_device_id=device.device_id,
                target_device_id=target_id,
                move_entity_ids=tuple(device.entity_ids),
                repoint_device_ids=tuple(children_of.get(device.device_id, ())),
            )
        )

    return MigrationPlan(renames=tuple(renames), merges=tuple(merges))


# ---------------------------------------------------------------------------
#  0.6.3: one device per lock
# ---------------------------------------------------------------------------
#
# Until 0.6.2 the authorization switches sat on a second device, "Nuki Web
# <lock>" (identifier (DOMAIN, "web_<id>"), via_device = the lock). Upstream
# added it in 2021 ("Expose Web API as device") to group the Web API switches;
# it is the same physical lock, so 0.6.3 puts every entity on the lock device
# and removes the Web API one. Entity ids, names set in Home Assistant, labels
# and categories live on the entity registry entries and are untouched.

WEB_PREFIX = "web_"


@dataclass(frozen=True)
class WebMerge:
    """Move the Web API device's entities onto the lock device, then drop it.

    `keep_area` pins an entity to the Web API device's area when it had none of
    its own and the lock device sits elsewhere, so no entity changes area.
    `disable_by_device` / `disable_by_user` keep each entity's enabled state
    consistent with its new device (Home Assistant's own rules on device
    disable/enable).
    """

    source_device_id: str
    target_device_id: str
    move_entity_ids: tuple[str, ...] = ()
    keep_area: tuple[tuple[str, str], ...] = ()
    disable_by_device: tuple[str, ...] = ()
    disable_by_user: tuple[str, ...] = ()


@dataclass(frozen=True)
class WebRename:
    """No lock device registered (should not happen): the Web API device
    becomes the lock device by taking the lock's identifier."""

    device_id: str
    new_identifiers: frozenset[Identifier]


@dataclass(frozen=True)
class WebMergePlan:
    merges: tuple[WebMerge, ...] = ()
    renames: tuple[WebRename, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.merges and not self.renames


@dataclass(frozen=True)
class EntityRow:
    entity_id: str
    area_id: str | None = None
    disabled_by: str | None = None  # "user", "device", "integration", … or None


def _lock_value(web_value: str):
    """The lock identifier value for a "web_<id>" one (nukiId is an int)."""
    raw = web_value[len(WEB_PREFIX):]
    return int(raw) if raw.isdigit() else raw


def plan_web_device_merge(
    devices: list[DeviceRow], entities: dict[str, EntityRow]
) -> WebMergePlan:
    """Plan folding every (DOMAIN, "web_<id>") device into the (DOMAIN, <id>) one.

    Empty once done, so it is safe on every start.
    """
    by_value: dict[str, DeviceRow] = {}
    for device in devices:
        for domain, value in device.identifiers:
            if domain == DOMAIN and not str(value).startswith(WEB_PREFIX):
                by_value[str(value)] = device

    merges: list[WebMerge] = []
    renames: list[WebRename] = []
    for device in devices:
        web = [
            v for d, v in device.identifiers
            if d == DOMAIN and str(v).startswith(WEB_PREFIX)
        ]
        if not web:
            continue
        lock_value = _lock_value(str(web[0]))
        target = by_value.get(str(lock_value))
        if target is None or target.device_id == device.device_id:
            renames.append(
                WebRename(
                    device_id=device.device_id,
                    new_identifiers=frozenset(
                        {i for i in device.identifiers if i[1] not in web}
                        | {(DOMAIN, lock_value)}
                    ),
                )
            )
            continue

        keep_area, by_device, by_user = [], [], []
        for entity_id in device.entity_ids:
            row = entities.get(entity_id, EntityRow(entity_id))
            if row.area_id is None and device.area_id and device.area_id != target.area_id:
                keep_area.append((entity_id, device.area_id))
            if target.disabled and row.disabled_by is None:
                by_device.append(entity_id)
            elif not target.disabled and row.disabled_by == "device":
                # The user had disabled the Web API device; keep its entities off.
                by_user.append(entity_id)
        merges.append(
            WebMerge(
                source_device_id=device.device_id,
                target_device_id=target.device_id,
                move_entity_ids=tuple(device.entity_ids),
                keep_area=tuple(keep_area),
                disable_by_device=tuple(by_device),
                disable_by_user=tuple(by_user),
            )
        )
    return WebMergePlan(merges=tuple(merges), renames=tuple(renames))


def _rows(hass, entry):
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)
    rows, entities = [], {}
    for device in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        ents = er.async_entries_for_device(
            entity_reg, device.id, include_disabled_entities=True
        )
        for e in ents:
            entities[e.entity_id] = EntityRow(
                e.entity_id, e.area_id, e.disabled_by.value if e.disabled_by else None
            )
        rows.append(
            DeviceRow(
                device_id=device.id,
                identifiers=frozenset(device.identifiers),
                via_device_id=device.via_device_id,
                entity_ids=tuple(e.entity_id for e in ents),
                area_id=device.area_id,
                disabled=device.disabled_by is not None,
            )
        )
    return rows, entities


async def async_migrate_device_registry(hass, entry):
    """Bring the registry for `entry` onto today's scheme: legacy identifier
    domains first, then one device per lock."""
    rows, _ = _rows(hass, entry)
    plan = plan_identifier_migration(rows)
    if not plan.is_empty:
        _apply_identifier_plan(hass, plan)
    rows, entities = _rows(hass, entry)
    web_plan = plan_web_device_merge(rows, entities)
    if not web_plan.is_empty:
        _apply_web_plan(hass, web_plan)
    return plan, web_plan


def _apply_web_plan(hass, plan: WebMergePlan) -> None:
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)
    for merge in plan.merges:
        _LOGGER.info(
            "Moving %d entities from the Nuki Web device %s to the lock device %s",
            len(merge.move_entity_ids),
            merge.source_device_id,
            merge.target_device_id,
        )
        areas = dict(merge.keep_area)
        for entity_id in merge.move_entity_ids:
            changes = {"device_id": merge.target_device_id}
            if entity_id in areas:
                changes["area_id"] = areas[entity_id]
            if entity_id in merge.disable_by_device:
                changes["disabled_by"] = er.RegistryEntryDisabler.DEVICE
            elif entity_id in merge.disable_by_user:
                changes["disabled_by"] = er.RegistryEntryDisabler.USER
            entity_reg.async_update_entity(entity_id, **changes)
        device_reg.async_remove_device(merge.source_device_id)
    for rename in plan.renames:
        _LOGGER.info("Nuki Web device %s becomes the lock device", rename.device_id)
        device_reg.async_update_device(
            rename.device_id,
            new_identifiers=set(rename.new_identifiers),
            via_device_id=None,
        )


def _apply_identifier_plan(hass, plan: MigrationPlan) -> None:
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    for rename in plan.renames:
        _LOGGER.info(
            "Migrating device %s to identifiers %s",
            rename.device_id,
            sorted(map(str, rename.new_identifiers)),
        )
        device_reg.async_update_device(
            rename.device_id, new_identifiers=set(rename.new_identifiers)
        )

    for merge in plan.merges:
        _LOGGER.info(
            "Merging stale device %s into %s (%d entities, %d children)",
            merge.source_device_id,
            merge.target_device_id,
            len(merge.move_entity_ids),
            len(merge.repoint_device_ids),
        )
        for entity_id in merge.move_entity_ids:
            entity_reg.async_update_entity(
                entity_id, device_id=merge.target_device_id
            )
        for child_id in merge.repoint_device_ids:
            device_reg.async_update_device(
                child_id, via_device_id=merge.target_device_id
            )
        device_reg.async_remove_device(merge.source_device_id)
