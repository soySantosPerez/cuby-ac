from __future__ import annotations

import logging
from typing import Any, Optional, Dict, List

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import CubyCoordinator
from .api import CubyApi, CubyApiError

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0

SUPPORTED_HVAC_MODES = [
    HVACMode.OFF,
    HVACMode.COOL,
    HVACMode.HEAT,
    HVACMode.FAN_ONLY,
    HVACMode.DRY,
    HVACMode.AUTO,
]
SUPPORTED_FAN_MODES = ["auto", "low", "medium", "high"]

SUPPORTED_FEATURES = (
    ClimateEntityFeature.TARGET_TEMPERATURE
    | ClimateEntityFeature.TURN_ON
    | ClimateEntityFeature.TURN_OFF
    | ClimateEntityFeature.FAN_MODE
)

# -------------------------
# Helpers
# -------------------------
def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None

def _extract_id(d: Dict[str, Any]) -> Optional[str]:
    for k in ("id", "deviceId", "uuid", "device_id"):
        val = d.get(k)
        if val is not None and str(val).strip():
            return str(val)
    return None

# -------------------------
# Platform setup function
# -------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Cuby climate entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    api: CubyApi = data["api"]
    coordinator: CubyCoordinator = data["coordinator"]
    token: str = entry.data["token"]

    selected_ids: Optional[List[str]] = entry.options.get("device_ids", entry.data.get("device_ids", None))

    devices = coordinator.data or []
    _LOGGER.debug(
        "Building climate entities from %s devices; selected_ids=%s (None=all, []=none)",
        len(devices),
        selected_ids,
    )

    if isinstance(selected_ids, list) and len(selected_ids) == 0:
        _LOGGER.debug("User selected no devices; creating 0 entities.")
        async_add_entities([])
        return

    entities: List[CubyDeviceClimate] = []
    for dev in devices:
        if not isinstance(dev, dict):
            continue
        dev_id = _extract_id(dev)
        if not dev_id:
            continue
        if isinstance(selected_ids, list) and dev_id not in selected_ids:
            continue
        name = dev.get("name") or dev.get("alias") or f"Cuby Device {dev_id}"
        entities.append(CubyDeviceClimate(coordinator, api, token, dev_id, name))

    _LOGGER.debug("Adding %s climate entities", len(entities))
    async_add_entities(entities)


# -------------------------
# Entity
# -------------------------
class CubyDeviceClimate(CoordinatorEntity[CubyCoordinator], ClimateEntity):
    """Representation of a Cuby A/C as a Home Assistant climate entity."""

    _attr_supported_features = SUPPORTED_FEATURES
    _attr_hvac_modes = SUPPORTED_HVAC_MODES
    _attr_min_temp = 16
    _attr_max_temp = 30
    _attr_hvac_mode = HVACMode.OFF
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_current_temperature: Optional[float] = None
    _attr_target_temperature: Optional[float] = None
    _attr_fan_modes = SUPPORTED_FAN_MODES
    _attr_fan_mode: str | None = None

    def __init__(self, coordinator: CubyCoordinator, api: CubyApi, token: str, device_id: str, name: str) -> None:
        super().__init__(coordinator)
        self._api = api
        self._token = token
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{device_id}"

        self._apply_payload(self._device_payload())

    # ----- Device Registry -----
    @property
    def device_info(self) -> DeviceInfo:
        d = self._device_payload() or {}
        model = d.get("model", "Cuby Smart AC Controller")
        fw = str(d.get("firmwareVersion") or d.get("fw") or d.get("firmware") or "unknown")
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._attr_name or "Cuby Device",
            manufacturer="Cuby",
            model=str(model),
            sw_version=fw,
            via_device=(DOMAIN, self.coordinator.config_entry.entry_id),
        )

    # ----- Helpers -----
    def _device_payload(self) -> Dict[str, Any] | None:
        """Return the current device dict from coordinator.data by id."""
        for d in self.coordinator.data or []:
            if isinstance(d, dict) and _extract_id(d) == self._device_id:
                return d
        return None

    def _apply_payload(self, device: Dict[str, Any] | None) -> None:
        """Map coordinator payload to HA attributes."""
        d = device or {}
        last = d.get("lastState") or {}
        env = d.get("data") or {}

        # Unity
        units = str(last.get("units", "c")).strip().lower()
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS if units == "c" else UnitOfTemperature.FAHRENHEIT

        # Temperature
        self._attr_current_temperature = _safe_float(env.get("temperature"))
        tgt = _safe_float(last.get("temperature"))
        self._attr_target_temperature = tgt

        # HVAC
        power = str(last.get("power", "off")).lower()
        mode = str(last.get("mode", "auto")).lower()
        if power == "off":
            self._attr_hvac_mode = HVACMode.OFF
        else:
            self._attr_hvac_mode = {
                "cool": HVACMode.COOL,
                "heat": HVACMode.HEAT,
                "fan": HVACMode.FAN_ONLY,
                "dry": HVACMode.DRY,
                "auto": HVACMode.AUTO,
            }.get(mode, HVACMode.AUTO)
        
        # Fan mode (from device lastState)
        fan = str((last.get("fan") or "auto")).lower()
        if fan not in SUPPORTED_FAN_MODES:
            fan = "auto"
        self._attr_fan_mode = fan

    # ----- Coordinator hooks -----
    async def async_update(self) -> None:
        dev = self._device_payload()
        self._apply_payload(dev)

    # ----- Climate actions -----
    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        payload = {"type": "temperature", "temperature": int(round(float(temp)))}
        await self._post_state(payload)
        self._attr_target_temperature = int(round(float(temp)))
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return
        mode_map = {
            HVACMode.COOL: "cool",
            HVACMode.HEAT: "heat",
            HVACMode.FAN_ONLY: "fan",
            HVACMode.DRY: "dry",
            HVACMode.AUTO: "auto",
        }
        payload = {"type": "mode", "mode": mode_map.get(hvac_mode, "auto"), "power": "on"}
        await self._post_state(payload)
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        await self._post_state({"type": "power", "power": "on"})
        # Default mode when turning on
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.AUTO
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        await self._post_state({"type": "power", "power": "off"})
        self._attr_hvac_mode = HVACMode.OFF
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan speed (auto/low/medium/high)."""
        fm = (fan_mode or "").lower()
        if fm not in SUPPORTED_FAN_MODES:
            _LOGGER.warning("[CUBY] Unsupported fan mode requested: %s", fan_mode)
            return

        payload = {"type": "fan", "fan": fm}
        await self._post_state(payload)

        # Reflect immediately in UI; coordinator refresh will confirm
        self._attr_fan_mode = fm
        self.async_write_ha_state()

    async def _post_state(self, payload: Dict[str, Any]) -> None:
        try:
            _LOGGER.debug("[CUBY] set_state(%s): %s", self._device_id, payload)
            await self._api.set_state(self._token, self._device_id, payload)
        except CubyApiError as err:
            _LOGGER.error("[CUBY] set_state failed for %s: %s", self._device_id, err)
            raise
        # Request refresh from coordinator to get updated state
        await self.coordinator.async_request_refresh()
