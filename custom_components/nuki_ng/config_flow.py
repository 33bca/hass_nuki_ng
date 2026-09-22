from homeassistant import config_entries
import homeassistant.helpers.config_validation as cv
from homeassistant.core import callback
from homeassistant.helpers.network import get_url
from .constants import DOMAIN
from .nuki import NukiInterface

import logging
import voluptuous as vol

_LOGGER = logging.getLogger(__name__)


class NukiNGConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    async def async_step_reauth(self, user_input):
        return await self.async_step_user(user_input)

    async def find_nuki_devices(self, config: dict):
        nuki = NukiInterface(
            self.hass,
            bridge=config.get("address"),
            token=config.get("token"),
            web_token=config.get("web_token")
        )
        title = None
        use_hashed_token = False
        if nuki.token:
            hass_url = config.get("hass_url", "")
            if hass_url.lower().startswith("https://"):
                _LOGGER.error(
                    f"Bridge doesn't support HTTPS callback URLs: {hass_url}")
                return title, "https_not_supported", None
            try:
                info = await nuki.bridge_info()
                use_hashed_token = info.get("bridgeType") == 1
                response = await nuki.bridge_list()
                _LOGGER.debug(f"bridge devices: {response}")
                first_device = next(iter(response.values()), {})
                title = first_device.get("name")
                if not title:
                    return title, "invalid_bridge_token", None
            except Exception as err:
                _LOGGER.exception(
                    f"Failed to get list of devices from bridge: {err}")
                return title, "invalid_bridge_token", None
        if nuki.web_token:
            try:
                response = await nuki.web_list()
                _LOGGER.debug(f"web devices: {response}")
                if not title:
                    first_device = next(iter(response.values()), {})
                    title = first_device.get("name")
            except Exception as err:
                _LOGGER.exception(
                    f"Failed to get list of devices from web API: {err}")
                return title, "invalid_web_token", None
        return title, None, use_hashed_token

    def _get_hass_url(self, hass):
        try:
            return get_url(hass)
        except Exception as err:
            _LOGGER.exception(f"Error getting HASS url: {err}")
            return ""

    async def async_step_user(self, user_input):
        errors = None
        _LOGGER.debug(f"Input: {user_input}")
        if user_input is None:
            nuki = NukiInterface(self.hass)
            bridge_address = await nuki.discover_bridge()
            hass_url = self._get_hass_url(self.hass)
            user_input = {
                "address": bridge_address,
                "hass_url": hass_url
            }
        elif not user_input.get("token") and not user_input.get("web_token"):
            errors = dict(base="no_token")
        elif user_input.get("token") and not user_input.get("address"):
            errors = dict(base="no_bridge_url")
        elif user_input.get("token") or user_input.get("web_token"):
            title, err, use_hashed_token = await self.find_nuki_devices(user_input)
            if not err:
                return self.async_create_entry(
                    title=user_input.get("name") or title,
                    data={
                        **user_input,
                        "use_hashed": use_hashed_token,
                    }
                )
            errors = dict(base=err)
        schema = vol.Schema({
            vol.Optional("address", default=user_input.get("address", "")): cv.string,
            vol.Optional("hass_url", default=user_input.get("hass_url", "")): cv.string,
            vol.Optional("token", default=user_input.get("token", "")): cv.string,
            vol.Optional("web_token", default=user_input.get("web_token", "")): cv.string,
            vol.Optional("name", default=user_input.get("name", "")): cv.string,
            vol.Required("update_seconds", default=user_input.get("update_seconds", 30)): vol.All(
                cv.positive_int,
                vol.Range(min=10, max=600)
            ),
        })
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):

    def __init__(self, config_entry):
        # Not self.config_entry: newer Home Assistant versions provide that property themselves
        self._entry = config_entry

    async def async_step_init(self, user_input=None):
        current = {**self._entry.data, **self._entry.options}
        errors = None
        if user_input is not None:
            # An emptied field keeps the value from the initial setup
            user_input = {k: v for k, v in user_input.items() if v != ""}
            token = user_input.get("token", current.get("token"))
            if current.get("address") and token:
                nuki = NukiInterface(
                    self.hass,
                    bridge=current.get("address"),
                    token=token,
                    use_hashed=user_input.get("use_hashed", False),
                )
                try:
                    await nuki.bridge_info()
                except Exception as err:
                    _LOGGER.warning(f"Bridge check with the new options failed: {err}")
                    errors = dict(base="hashed_token_rejected" if user_input.get("use_hashed") else "invalid_bridge_token")
            if not errors:
                return self.async_create_entry(title="", data=user_input)
            current = {**current, **user_input}
        fields = {}
        if current.get("address"):
            fields[vol.Optional("token", default=current.get("token", ""))] = cv.string
            fields[vol.Required("use_hashed", default=self._entry.options.get("use_hashed", False))] = cv.boolean
        fields[vol.Required("update_seconds", default=current.get("update_seconds", 30))] = vol.All(
            cv.positive_int,
            vol.Range(min=10, max=600)
        )
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(fields), errors=errors
        )
