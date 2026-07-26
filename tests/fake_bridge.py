#!/usr/bin/env python3
"""Stand-in for a Nuki Hardware Bridge and the Nuki Web API.

Serves just enough of both to let the integration set up, so the device
registry migration can be exercised end-to-end without touching real hardware.
A second client on the real bridge is not harmless: `bridge_check_callback`
deletes every callback it does not find in first position and re-adds its own,
so two Home Assistant instances would fight over the callback list every poll.

    python3 fake_bridge.py [--port 8099] [--lock-id 824523165]

Endpoints — bridge: /info /list /callback/list /callback/add /callback/remove
            web:    /smartlock /smartlock/<id>/auth
"""

from __future__ import annotations

import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOG = logging.getLogger("fake_bridge")

STATE = {
    "lock_id": 824523165,
    "bridge_id": 485731010,
    "callbacks": [],
    "next_callback_id": 0,
}


def bridge_info() -> dict:
    return {
        "bridgeType": 1,
        "ids": {"hardwareId": STATE["bridge_id"], "serverId": 1234567},
        "versions": {"firmwareVersion": "2.18.0", "wifiFirmwareVersion": "2.4.0"},
        "uptime": 987654,
        "currentTime": "2026-07-26T08:00:00+00:00",
        "serverConnected": True,
        "scanResults": [],
    }


def device_list() -> list:
    return [
        {
            "deviceType": 0,
            "nukiId": STATE["lock_id"],
            "name": "Zuhause",
            "firmwareVersion": "3.10.7",
            "lastKnownState": {
                "mode": 2,
                "state": 1,
                "stateName": "locked",
                "batteryCritical": False,
                "batteryCharging": False,
                "batteryChargeState": 60,
                "keypadBatteryCritical": False,
                "doorsensorState": 3,
                "doorsensorStateName": "door closed",
                "timestamp": "2026-07-26T08:00:00+00:00",
            },
        }
    ]


def web_smartlocks() -> list:
    return [
        {
            "smartlockId": STATE["lock_id"],
            "type": 0,
            "name": "Zuhause",
            "firmwareVersion": 197127,
            "state": {"state": 1, "batteryCharge": 60, "doorState": 3},
            "config": {"name": "Zuhause", "buttonEnabled": True},
            "advancedConfig": {"autoLock": False},
            "web": True,
        }
    ]


def web_auths() -> list:
    # Two entries so the Web API device is guaranteed to exist and carry
    # entities during the migration.
    return [
        {"id": "auth-sonja", "name": "Sonja", "enabled": True, "type": 0,
         "remoteAllowed": True, "lockCount": 42},
        {"id": "auth-christian", "name": "Christian", "enabled": True, "type": 0,
         "remoteAllowed": True, "lockCount": 17},
    ]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)
        LOG.info("GET %s", self.path)

        if path == "/info":
            return self._send(bridge_info())
        if path == "/list":
            return self._send(device_list())
        if path == "/callback/list":
            return self._send({"callbacks": STATE["callbacks"]})
        if path == "/callback/add":
            url = query.get("url", [""])[0]
            STATE["callbacks"].append({"id": STATE["next_callback_id"], "url": url})
            STATE["next_callback_id"] += 1
            return self._send({"success": True})
        if path == "/callback/remove":
            cb_id = int(query.get("id", ["-1"])[0])
            STATE["callbacks"] = [c for c in STATE["callbacks"] if c["id"] != cb_id]
            return self._send({"success": True})
        if path == "/smartlock":
            return self._send(web_smartlocks())
        if path.startswith("/smartlock/") and path.endswith("/auth"):
            return self._send(web_auths())
        if path.startswith("/smartlock/") and path.endswith("/log"):
            # Must be a list: the caller iterates and calls .get() per entry.
            return self._send([])
        if path.startswith("/smartlock/"):
            return self._send(web_smartlocks()[0])

        LOG.warning("unhandled path %s", self.path)
        return self._send({"error": "not found", "path": self.path}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        LOG.info("POST %s", self.path)
        return self._send({"success": True})

    def log_message(self, fmt, *args):  # quieter default logging
        LOG.debug(fmt, *args)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--lock-id", type=int, default=STATE["lock_id"])
    ap.add_argument("--bridge-id", type=int, default=STATE["bridge_id"])
    args = ap.parse_args()

    STATE["lock_id"] = args.lock_id
    STATE["bridge_id"] = args.bridge_id

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    LOG.info(
        "fake bridge on :%d — lock %s, bridge %s",
        args.port, STATE["lock_id"], STATE["bridge_id"],
    )
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
