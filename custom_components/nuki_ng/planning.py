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


def auth_object_id(device_name: str, auth: dict, auth_id) -> str:
    """Entity id suggestion for a NEW authorization switch.

    Ends with the Nuki auth id, so an entity id keeps naming the same Nuki
    entry even after the entry is renamed. Ids already in the entity registry
    are never changed by this.
    """
    name = auth.get("name") or "undefined"
    return f"Nuki {device_name} authorization {name} {auth.get('authId') or auth_id}"


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
