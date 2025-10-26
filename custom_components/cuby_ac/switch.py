from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import CubyCoordinator
from .api import CubyApi, CubyApiError

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0

# Each tuple: (key_in_lastState, type_value, human_name)
SWITCH_SPECS = [
    ("eco",     "eco",     "Eco"),
    ("turbo",   "turbo",   "Turbo"),  
    ("long",    "long",    "Long"),
]

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Cuby switch entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    api: CubyApi = data["api"]
    coordinator: CubyCoordinator = data["coordinator"]
    token: str = entry.data["token"]

    selected_ids: Optional[List[str]] = entry.options.get("device_ids", entry.data.get("device_ids", None))
    devices = coordinator.data or []

    entities: List[CubyToggleSwitch] = []
    for dev in devices:
        if not isinstance(dev, dict):
            continue
        dev_id = str(dev.get("id") or "").strip()
        if not dev_id:
            continue
        if isinstance(selected_ids, list) and dev_id not in selected_ids:
            continue

        base_name = dev.get("name") or f"Cuby {dev_id}"
        for (state_key, type_key, human) in SWITCH_SPECS:
            entities.append(
                CubyToggleSwitch(
                    coordinator=coordinator,
                    api=api,
                    token=token,
                    device_id=dev_id,
                    device_name=base_name,
                    state_key=state_key,
                    type_key=type_key,
                    friendly_name=f"{base_name} {human}",
                )
            )

    _LOGGER.debug("Adding %s switch entities", len(entities))
    async_add_entities(entities)


class CubyToggleSwitch(CoordinatorEntity[CubyCoordinator], SwitchEntity):
    """Generic ON/OFF switch for a lastState boolean-like flag."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: CubyCoordinator,
        api: CubyApi,
        token: str,
        device_id: str,
        device_name: str,
        state_key: str,
        type_key: str,
        friendly_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._token = token
        self._device_id = device_id
        self._device_name = device_name
        self._state_key = state_key      # key in lastState: "eco"/"turbo"/"long"
        self._type_key = type_key
        self._attr_name = friendly_name
        icon_map = {
            "eco": "mdi:leaf",
            "turbo": "mdi:run-fast",
            "long": "mdi:weather-windy",
        }
        self._attr_icon = icon_map.get(self._state_key, "mdi:tune-variant")
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{state_key}"

        # initial
        self._attr_is_on = self._read_is_on()

    # ----- Helpers -----
    def _device_payload(self) -> Dict[str, Any] | None:
        for d in self.coordinator.data or []:
            if isinstance(d, dict) and str(d.get("id") or "").strip() == self._device_id:
                return d
        return None

    def _read_is_on(self) -> bool:
        dev = self._device_payload() or {}
        last = dev.get("lastState") or {}
        val = str((last.get(self._state_key) or "off")).lower()
        return val == "on"

    # ----- SwitchEntity API -----
    @property
    def is_on(self) -> bool:
        return self._read_is_on()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._post_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._post_state(False)

    async def _post_state(self, turn_on: bool) -> None:
        payload = {"type": self._type_key, self._state_key: "on" if turn_on else "off"}
        try:
            _LOGGER.debug("[CUBY] set_state(%s): %s", self._device_id, payload)
            await self._api.set_state(self._token, self._device_id, payload)
        except CubyApiError as err:
            _LOGGER.error("[CUBY] set_state failed for %s: %s", self._device_id, err)
            raise
        # reflect & refresh
        self._attr_is_on = turn_on
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    # ----- Device registry -----
    @property
    def device_info(self) -> DeviceInfo:
        d = self._device_payload() or {}
        model = d.get("model", "Cuby Smart AC Controller")
        fw = str(d.get("firmwareVersion") or "unknown")
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer="Cuby",
            model=str(model),
            sw_version=fw,
            via_device=(DOMAIN, self.coordinator.config_entry.entry_id),
        )
