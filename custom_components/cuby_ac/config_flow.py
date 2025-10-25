from __future__ import annotations
import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .api import CubyApi, CubyAuthError, CubyApiError, TOKEN_TTL_SECONDS

_LOGGER = logging.getLogger(__name__)

@config_entries.HANDLERS.register(DOMAIN)
class ConfigFlow(config_entries.ConfigFlow):
    """Handle Cuby AC config flow."""
    VERSION = 1
    _username: str | None = None
    _token: str | None = None
    _devices_cache: list[dict] | None = None

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input["username"].strip()
            password = user_input["password"]

            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            api = CubyApi(session)

            try:
                auth = await api.get_token(username, password, TOKEN_TTL_SECONDS)
                devices = await api.get_devices(auth["token"])
            except CubyAuthError:
                _LOGGER.debug("Invalid credentials for user %s", username)
                errors["base"] = "invalid_auth"
            except CubyApiError as exc:
                _LOGGER.warning("Cuby API error during login/devices: %s", exc)
                errors["base"] = "cannot_connect"
            except Exception as exc:
                _LOGGER.exception("Unexpected error during login/devices: %s", exc)
                errors["base"] = "unknown"
            else:
                self._username = username
                self._token = auth["token"]
                self._devices_cache = devices or []
                return await self.async_step_select_devices()

        schema = vol.Schema({
            vol.Required("username"): str,
            vol.Required("password"): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_select_devices(self, user_input: dict | None = None) -> FlowResult:
        devices = self._devices_cache or []
        options: dict[str, str] = {}
        for d in devices:
            dev_id = str(d.get("id") or d.get("deviceId") or d.get("uuid") or "")
            if not dev_id:
                continue
            name = d.get("name") or d.get("alias") or f"Cuby Device {dev_id}"
            options[dev_id] = f"{name} ({dev_id})"

        if user_input is not None:
            selected: list[str] = user_input.get("devices", [])
            return self.async_create_entry(
                title=self._username or "Cuby Account",
                data={
                    "username": self._username,
                    "token": self._token,
                    "device_ids": selected,
                },
            )

        default = list(options.keys())
        schema = vol.Schema({
            vol.Required("devices", default=default): cv.multi_select(options)
        })
        return self.async_show_form(step_id="select_devices", data_schema=schema)

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow to add/remove devices later."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._devices_cache: list[dict] | None = None

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        """Entry point for options."""
        # Fetch current devices from API using stored token
        token: str = self._entry.data.get("token")
        session = async_get_clientsession(self.hass)
        api = CubyApi(session)

        try:
            devices = await api.get_devices(token)
        except Exception as exc:
            devices = []
            _LOGGER.warning("Could not fetch devices during options: %s", exc)

        self._devices_cache = devices or []
        return await self.async_step_pick_devices()

    async def async_step_pick_devices(self, user_input: dict | None = None) -> FlowResult:
        devices = self._devices_cache or []
        options_map: dict[str, str] = {}
        for d in devices:
            dev_id = str(d.get("id") or d.get("deviceId") or d.get("uuid") or "")
            if not dev_id:
                continue
            name = d.get("name") or d.get("alias") or f"Cuby Device {dev_id}"
            options_map[dev_id] = f"{name} ({dev_id})"

        current = self._entry.options.get("device_ids") or self._entry.data.get("device_ids") or []

        if user_input is not None:
            selected: list[str] = user_input.get("devices", [])
            return self.async_create_entry(data={"device_ids": selected})

        schema = vol.Schema({
            vol.Required("devices", default=current): cv.multi_select(options_map)
        })
        return self.async_show_form(step_id="pick_devices", data_schema=schema)
