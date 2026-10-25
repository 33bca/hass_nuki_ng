"""Pure helpers with no Home Assistant imports, so they can be unit-tested alone."""

from __future__ import annotations

from datetime import timedelta

BRIDGE_CALLBACK_SLOTS = 3
BRIDGE_CALLBACK_CHECK = timedelta(minutes=5)

# Nuki Web API authorization types
AUTH_TYPES = {
    0: "app",
    1: "bridge",
    2: "fob",
    3: "keypad",
    13: "keypad code",
    14: "z-key",
    15: "virtual",
}

AUTH_ICONS = {
    0: "mdi:devices",
    1: "mdi:network",
    2: "mdi:remote",
    3: "mdi:focus-field",
    13: "mdi:form-textbox-password",
}


def plan_callback_changes(callbacks_list: list, callback: str) -> dict:
    """Decide which bridge callbacks to remove and whether ours must be added.

    Keeps the lowest-id copy of our URL, removes the other copies (highest id
    first, as the bridge renumbers ids after a removal) and never evicts
    callbacks that belong to someone else.
    """
    ours = sorted(item["id"] for item in callbacks_list if item.get("url") == callback)
    remove_ids = sorted(ours[1:], reverse=True)
    add = not ours
    full = add and len(callbacks_list) >= BRIDGE_CALLBACK_SLOTS
    return dict(remove_ids=remove_ids, add=add, full=full)


def auth_attributes(auth: dict) -> dict:
    """State attributes for an authorization switch.

    An explicit allow-list: the Web API entry also holds the keypad PIN
    ("code"), which must never reach the state machine.
    """
    auth_type = auth.get("type")
    fingerprints = auth.get("fingerprints") or {}
    return {
        "Nuki name": auth.get("name"),
        "Auth ID": auth.get("authId"),
        "Type": AUTH_TYPES.get(auth_type, auth_type),
        "Fingerprints": len(fingerprints) if isinstance(fingerprints, (dict, list)) else None,
        "Remote allowed": auth.get("remoteAllowed"),
        "Lock count": auth.get("lockCount"),
        "Last active date": auth.get("lastActiveDate"),
    }


def auth_object_id(auth: dict, auth_id) -> str:
    """Entity id suggestion for a NEW authorization switch (HA adds the device name).

    Ends with the Nuki auth id, so an entity id keeps naming the same Nuki
    entry even after the entry is renamed. Ids already in the entity registry
    are never changed by this.
    """
    name = auth.get("name") or "undefined"
    return f"{name} {auth.get('authId') or auth_id}"


def removed_auths(known: set, device_auths: dict, fetched_ok: dict) -> set:
    """(device, auth) pairs that disappeared from a successful Web API fetch.

    A device whose fetch failed, or that suddenly reports no entries at all
    while we knew some, is skipped: an outage must never drop switches.
    """
    gone = set()
    for dev_id, auth_id in known:
        if not fetched_ok.get(dev_id):
            continue
        current = device_auths.get(dev_id) or {}
        if not current:
            continue
        if auth_id not in current:
            gone.add((dev_id, auth_id))
    return gone


LOCK_ACTIONS = frozenset({"unlock", "lock", "open", "lock_n_go", "lock_n_go_open"})
OPENER_ACTIONS = frozenset({
    "activate_rto",
    "deactivate_rto",
    "electric_strike_actuation",
    "activate_continuous_mode",
    "deactivate_continuous_mode",
})


def action_mismatches(action: str, devices: dict) -> list:
    """Device ids the action must NOT be sent to.

    `devices` maps device id -> "lock" | "opener" | other. Opener actions share
    the numeric codes of lock actions (activate_rto = 1 = unlock), so sending
    one to the wrong kind of device does something else entirely.
    """
    if action in LOCK_ACTIONS:
        wanted = "lock"
    elif action in OPENER_ACTIONS:
        wanted = "opener"
    else:
        return sorted(devices, key=str)
    return sorted((d for d, kind in devices.items() if kind != wanted), key=str)


def devices_to_sync(dev_ids, disabled) -> list:
    """Devices to ask Nuki Web to sync at setup: every one not disabled in HA."""
    return [dev_id for dev_id in dev_ids if dev_id not in disabled]


# Nuki Web (api.nuki.io) fields; everything else comes from the bridge when there is one.
WEB_CONFIG_FIELDS = ("config", "advancedConfig", "openerAdvancedConfig")
WEB_POLL_FIELDS = ("web_auth", "last_unlock_log", "last_log")
# After Nuki Web fails, the bridge keeps being polled as usual and Nuki Web is
# asked again only after this, so a cloud outage does not slow every poll down.
WEB_RETRY = timedelta(minutes=2)


def web_due(failed_at, now) -> bool:
    """Whether to call Nuki Web on this poll (never failed, or WEB_RETRY passed)."""
    return failed_at is None or now - failed_at >= WEB_RETRY


def carry_web_data(item: dict, previous: dict) -> dict:
    """Fill the Nuki Web fields of a bridge item from the last good poll.

    Used when Nuki Web did not answer: entities built on those fields keep
    their last value instead of flapping, and the authorization switches are
    marked not freshly fetched (so none is released as deleted).
    """
    for field in WEB_CONFIG_FIELDS:
        if item.get(field) is None and previous.get(field) is not None:
            item[field] = previous[field]
    for field in WEB_POLL_FIELDS:
        item.setdefault(field, previous.get(field, {}))
    item["web_auth_ok"] = False
    return item


# Settings the reconfigure step can change. A blank field keeps the current value.
RECONFIGURE_FIELDS = ("address", "hass_url", "token", "web_token")


def plan_reconfigure(data: dict, options: dict, user_input: dict):
    """Split a reconfigure form into entry-data updates and the new options.

    Options override the data at setup, so a value set here is removed from the
    options (only the bridge token can be in both), or it would not apply.
    Returns (data_updates, options).
    """
    current = {**data, **options}
    updates = {
        key: value
        for key in RECONFIGURE_FIELDS
        if (value := user_input.get(key)) not in (None, "") and value != current.get(key)
    }
    new_options = {key: value for key, value in options.items() if key not in updates}
    return updates, new_options


def effective_config(data: dict, updates: dict, options: dict) -> dict:
    """The configuration setup will use after a reconfigure."""
    return {**data, **updates, **options}


def is_same_bridge(known_bridge_ids: set, hardware_id) -> bool:
    """Whether the bridge at the new address is the one this entry already knows.

    No known bridge (Web-only entry, or the bridge never answered) → nothing to compare.
    """
    if not known_bridge_ids:
        return True
    return hardware_id is not None and str(hardware_id) in {str(i) for i in known_bridge_ids}
