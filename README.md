[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)


> **Maintained fork of [kvj/hass_nuki_ng](https://github.com/kvj/hass_nuki_ng).**
> Same integration domain (`nuki_ng`), so existing installs, devices and entity ids carry over.
> It gathers the open upstream pull requests and fork fixes, plus fixes nobody had shipped yet.
> Requires Home Assistant 2026.10 or newer.

### 0.6.5
* *Reconfigure* (integration entry → ⋮ → Reconfigure): change the bridge address, the Home Assistant URL, the bridge token or the Web API token of an existing entry, e.g. after the bridge got a new IP address. Checked against the bridge before saving; a different bridge is refused, so devices and entity ids stay the same (upstream #236, #140, #206, #18)
* Setup no longer fails when Nuki Web (api.nuki.io) is down while the bridge works: the bridge entities start, Nuki Web data keeps its last value and Nuki Web is retried every 2 minutes; its entities appear once it answers. Nuki Web requests time out after 20 s instead of hanging (upstream #229, #226, #200)
* `iot_class` is `local_push`: with a bridge, state changes arrive through the bridge callback, polling is only the fallback (upstream #10, PR #15)

### 0.6.4
* "Last Log" and "Last Unlock user" sensors exist for every lock/opener when the Nuki Web API is configured (before, only if the Nuki Web activity log already had a matching entry at the first poll)

### 0.6.3
* One device per lock/opener: the authorization switches move from the separate "Nuki Web <lock>" device onto the lock's own device, and the empty Web API device is removed (registry migration at start; entity ids, names set in HA, entity labels and categories and enabled/disabled state are kept, the Web API device's labels are added to the lock device; switches without an area of their own now show the lock's area). Automations that used the Web API device by its device id must use the lock device; the log names the removed device
* Every entity uses Home Assistant entity naming: the name shown is "<device name> <entity name>", so renaming the device in HA renames all its entities (a name set on an entity in HA still wins). The lock entity shows just the device name; the device's default name is the name from the Nuki app (no extra "Nuki" prefix)

### 0.6.2
* Authorization switch names follow the entry's current name in the Nuki app / Nuki Web again (a name set in Home Assistant still wins; entity ids never change). "Recreate entity IDs" in HA then gives ids such as `..._guest_finger_8198`
* Sync button and button-press selects use Home Assistant entity naming, so a renamed lock no longer shows its name twice
* After an authorization switch changes an entry, Nuki Web is asked to sync with the lock (one sync per burst of changes), then the entry is read back
* At setup, Nuki Web is asked to sync each enabled lock/opener once (disabled devices are skipped), so changes made on the lock (app, keypad, Nuki Hub) show up without pressing "Update now" in Nuki Web

### 0.6.1
* Authorization switches use Home Assistant entity naming (device name + entry name), so renaming the Web API device no longer turns their names into "Nuki <lock> authorization: <entry>"; names from older releases are converted

### Changes in 0.6.0 (vs upstream 0.5.5)

Merged from upstream PRs and forks (authorship kept in the git history):
* Device registry migration off the legacy `id`/`web_id` identifiers, device removal from the UI (PR #239, with tests)
* `via_device_id` instead of `via_device`, which HA removes in 2027.8 (Eric Guichard)
* Correct local state after toggling an authorization, Web API sync button, new locks/authorizations picked up without a reload, AuthEntry device fix (Ferdinand Berger)
* Single/double button press action selects (PR #242)
* Options flow: bridge token, hashed bridge token (opt-in), poll interval; tokens masked in errors (umstandsheini)

New in this fork:
* Services work again on HA 2026.10 (upstream #240)
* `execute_action` acts only on the targeted lock/opener; upstream sent it to every device of the entry, so an Opener action could lock a Smart Lock (upstream #237)
* The bridge keeps exactly one callback slot for this integration, checked every 5 minutes instead of every poll (upstream #245)
* Authorization switches: read back from the Web API 5 s after a change; names no longer change when the entry is renamed in the Nuki app; new switches carry the Nuki auth id in their entity id; attributes show the Nuki name, auth id, type and fingerprint count (never the PIN); switches of entries deleted in Nuki are released, so they can be removed
* Request errors never include the bridge token

Install: HACS → Custom repositories → `https://github.com/cmatte/hass_nuki_ng` (Integration). Replace the kvj repository if you had it.


## Better support for Nuki devices in Home Assistant

### Features:
* Supported modes:
  * Nuki Bridge-only, with automatic webhook registration
  * Cloud Web API, without Nuki bridge (Nuki Lock 3.0 Pro). Polling only
  * Hybrid, using best parts of both
* Exposes the detailed device information via sensors
* If supported, enables access control to Nuki authorization objects (keypad codes, accounts)
  
  
### Screenshots:
<img width="1020" alt="Screenshot 2021-10-11 at 14 02 42" src="https://user-images.githubusercontent.com/159124/136786951-d1ffdb22-637a-49c2-a1ff-43c465a03f0b.png">
  
  
## Setup

{% if not installed %}

### Installation:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cmatte&repository=hass_nuki_ng&category=integration)

* Go to HACS -> Integrations
* Click the three dots on the top right and select `Custom Repositories`
* Enter `https://github.com/cmatte/hass_nuki_ng` as repository, select the category `Integration` and click Add
* A new custom integration shows up for installation (Nuki Lock) - install it
* Restart Home Assistant

{% endif %}
  
### Configuration:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=nuki_ng)

* Go to Configuration -> Integrations
* Click `Add Integration`
* Search for `Nuki Lock` (not just `Nuki`, as this is the native integration from Home Assistant) and select it
* The integration will try to automatically discover your Nuki Bridge hostname or IP address, if you have a bridge
* It will also automatically enter the Home Assistant internal URL
* Provide either the Bridge API token and URL and/or a web API token and click Submit
* You can provide both, but you need to provide at least one
  
  
#### Changing the bridge address or tokens later:
Open the integration entry, click ⋮ and *Reconfigure*. Enter the new bridge hostname or IP address (and, if needed, a
new bridge or Web API token; leave a token blank to keep the current one). The bridge at the new address must be
the same bridge the entry already uses. The poll interval and the hashed-token setting stay under *Configure*.

#### Bridge API Token:
The API token for the Nuki Bridge needs to be configured on the bridge, e.g. using the Nuki mobile app. The
[Home Assistant Nuki documentation](https://www.home-assistant.io/integrations/nuki/) explains it like this:

> To add a Nuki bridge to your installation, you need to enable developer mode on your bridge and define a port and an access token. This can be achieved using the [Android app](https://play.google.com/store/apps/details?id=io.nuki) or [iPhone app](https://apps.apple.com/app/nuki-smart-lock/id1044998081). Go to manage my devices, and select the bridge. Within the bridge configuration turn on the HTTP API and check the details in the screen. Please note that the API token should be 6-20 characters long, even though the app allows you to set a longer one.

#### Hashed bridge token:
By default the bridge API token is sent in plain text as part of every request URL, so anyone who can sniff your
local network traffic can read it and control your lock. Hardware bridges also accept a
[hashed token](https://developer.nuki.io/page/nuki-bridge-http-api-1-13/4#heading--token) instead: each request
carries a timestamp, a random number and a SHA-256 hash, and the token itself never leaves Home Assistant.

* New entries created with a hardware bridge use the hashed token automatically.
* For existing entries: open the integration, click *Configure* and enable *Use hashed bridge token*. The setting is
  checked against the bridge before it is saved.
* The bridge needs a correct clock for this, which it gets via the internet. A bridge without internet access will
  reject hashed tokens - leave the option off in that case.
* Since the old token may have been visible on your network, consider generating a new one in the Nuki app and
  entering it in the same *Configure* dialog.
  
  
#### Web API Token:
* Go to the Nuki Web API management site at https://web.nuki.io/
* Nuki Web needs to be activated in the Nuki app - there is a link on the site that tells you how to do that
* Once activated, login on the web
* In the menu on the left, select API
* Click `Generate API token`
* Give it a name, leave the other settings as they are and click Save
* Copy the token and save it in a secure place. It will only be shown this once to you.
  
  
## Usage:

### Devices:

The integration provides several devices and entities to Home Assistant, depending on your setup. For example:

| Device            | Description                                                                                     |
|-------------------|-------------------------------------------------------------------------------------------------|
| Nuki Bridge       | Providing four diagnostic sensors about the state of the bridge.                                |
| Nuki Lock         | Providing one `lock` entity, three state sensors and eight diagnostic sensors about the lock.   |
| Nuki Opener       | Providing one `lock` entity, one state sensor and five diagnostic sensors about the opener.     |
| Nuki Web API      | Providing configuration `switch` entities for access permissions as set in the Nuki app.        |

In your setup, you could have several locks, but maybe no opener, no bridge or no web API.
  
  
### Entities:

#### Nuki Bridge:

| Entity ID                                      | Type        |  Description                                                               |
|------------------------------------------------|-------------|----------------------------------------------------------------------------|
| binary_sensor.nuki_bridge_bridge_callback_set  | Diagnostic  | On, if the integration successfully registered a callback with the bridge  |
| binary_sensor.nuki_bridge_connected            | Diagnostic  | On, if the bridge is reachable via WiFi                                    |
| sensor.nuki_bridge_firmware_version            | Diagnostic  | The current firmware version of the bridge                                 |
| sensor.nuki_bridge_wifi_firmware_version       | Diagnostic  | The current WiFi firmware version of the bridge                            |
  
  
#### Nuki Lock:

The entity IDs depend on the Nuki names of the lock. In the example below, it is `Wohnung`.

| Entity ID                                      | Type        | Description                                     |
|------------------------------------------------|-------------|-------------------------------------------------|
| lock.nuki_wohnung_lock                         | Control     | The main entity to control the lock             |
| binary_sensor.nuki_wohnung_door_open           | Sensor      | Shows the state of the door                     |
| binary_sensor.nuki_wohnung_locked              | Sensor      | Shows the state of the lock                     |
| sensor.nuki_wohnung_door_security_state        | Sensor      | Combines the state of the door with the lock    |
| sensor.nuki_wohnung_battery                    | Diagnostic  | Shows the battery level of the lock             |
| binary_sensor.nuki_wohnung_battery_charging    | Diagnostic  | Shows if the battery is currently charging      |
| binary_sensor.nuki_wohnung_battery_critical    | Diagnostic  | Shows if the battery has a critical level       |
| sensor.nuki_wohnung_door_state                 | Diagnostic  | Shows the state of the door                     |
| sensor.nuki_wohnung_firmware_version           | Diagnostic  | Shows the current firmware of the lock          |
| binary_sensor.nuki_wohnung_keypad_battery_critical | Diagnostic | Shows if the battery of the keypad has a critical level |
| sensor.nuki_wohnung_rssi                       | Diagnostic  | Shows the received signal strength indicator of the lock   |
| sensor.nuki_wohnung_state                      | Diagnostic  | Shows the state of the lock                     |
  
  
#### Nuki Opener:

The entity IDs depend on the Nuki names of the lock. In the example below, it is `Haustur`.

| Entity ID                                      | Type        | Description                                     |
|------------------------------------------------|-------------|-------------------------------------------------|
| lock.nuki_haustur_lock                         | Control     | The main entity to control the opener           |
| binary_sensor.nuki_haustur_locked              | Sensor      | Shows the state of the opener (locked or unlocked)  |
| binary_sensor.nuki_haustur_battery_critical    | Diagnostic  | Shows if the battery has a critical level       |
| sensor.nuki_haustur_firmware_version           | Diagnostic  | Shows the current firmware of the opener        |
| sensor.nuki_haustur_rssi                       | Diagnostic  | Shows the received signal strength indicator of the opener   |
| sensor.nuki_haustur_state                      | Diagnostic  | Shows the state of the opener (e.g., rto active)  |
  
  
#### Nuki Web API:

The entity IDs depend on the authorization you have given to your devices. There will be as many `switch` entities as
there are authorizations stored on the Nuki platform. While they are all named `switch.nuki_` followed by a descriptive
name, there are three different types:

| Type                                      | Example                                          |
|-------------------------------------------|--------------------------------------------------|
| Authorization of local devices            | The keypad, which is granted access to the lock  |
| Authorization of access codes             | A code registered with the keypad                |
| Authorization of apps                     | Access granted to members of the family          |
  
  
### Services:

The integration provides the following services:
  
  
#### Service `lock.lock` 

* For a Nuki Lock, this locks the door
* For a Nuki Opener, this stops an active ring-to-open function

The attribute should appear as a `target` for the service.

| Target attribute    | Optional | Description                                           |
|---------------------|----------|-------------------------------------------------------|
| `entity_id`         |       no | Entity of the relevant lock.                          |
  
  
#### Service `lock.unlock` 

* For a Nuki Lock, this unlocks the door
* For a Nuki Opener, this starts the ring-to-open function

The attribute should appear as a `target` for the service.

| Target attribute    | Optional | Description                                           |
|---------------------|----------|-------------------------------------------------------|
| `entity_id`         |       no | Entity of the relevant lock.                          |
  
  
#### Service `lock.open` 

* For a Nuki Lock, this unlatches the door
* For a Nuki Opener, this buzzes the door open

The attribute should appear as a `target` for the service.

| Target attribute    | Optional | Description                                           |
|---------------------|----------|-------------------------------------------------------|
| `entity_id`         |       no | Entity of the relevant lock.                          |
  
  
#### Service `nuki_ng.bridge_reboot` 

Reboots the Nuki Bridge. This service has no attributes
  
  
#### Service `nuki_ng.bridge_fwupdate` 

Performs a bridge software update. This service has no attributes
  
  
#### Service `nuki_ng.bridge_delete_callback` 

Deletes a callback URL from the bridge callbacks list.
The callbacks currently set are exposed as attributes of the 'Bridge Callback Set' entity.

The attribute should appear as a `target` for the service.

| Service data attribute    | Optional | Description                                           |
|---------------------------|----------|-------------------------------------------------------|
| `command`                 |       no | URL to delete.                                        |

## Useful tips

### Open/unlatch Nuki lock via UI

Even though the component supports the `lock.open` service and advertises support of it, Lovelace UI doesn't show any controls to trigger. This can be achieved via simple script similar to the one below:
```yaml
alias: Nuki Lock Open
sequence:
  - device_id: 8d159025411a270ecb9024794bc54361
    domain: lock
    entity_id: lock.nuki_front_door_lock
    type: open
mode: single
icon: mdi:lock-open
```

or manually calling the service:
```yaml
type: button
entity: lock.nuki_front_door_lock
tap_action:
  action: call-service
  service: lock.open
  service_data: {}
  target:
    entity_id: lock.nuki_front_door_lock
name: Nuki
```
