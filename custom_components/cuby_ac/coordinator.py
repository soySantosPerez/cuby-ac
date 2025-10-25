from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CubyApi, CubyApiError, CubyAuthError

_LOGGER = logging.getLogger(__name__)


def _index_by_id(devs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for d in devs or []:
        did = str(d.get("id") or "").strip()
        if did:
            out[did] = d
    return out


class CubyCoordinator(DataUpdateCoordinator[List[Dict[str, Any]]]):
    """Coordinator that keeps Cuby devices and state up to date."""

    def __init__(self, hass: HomeAssistant, api: CubyApi, token: str, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Cuby devices/state",
            update_interval=timedelta(seconds=60),
        )
        self._api = api
        self._token = token
        self._entry = entry  # to read device_ids from options/data dynamically

    def _selected_ids(self) -> Optional[List[str]]:
        """ Selected IDs by the user. None = all, [] = none."""
        selected = self._entry.options.get("device_ids", self._entry.data.get("device_ids", None))
        if isinstance(selected, list):
            return [str(x) for x in selected]
        return None  # None => all

    async def _async_update_data(self) -> List[Dict[str, Any]]:
        """Fetch devices list and enrich with per-device state."""
        try:
            devices = await self._api.get_devices(self._token)
            by_id = _index_by_id(devices)
            selected = self._selected_ids()

            # If the user explicitly chose "none", return empty list
            if isinstance(selected, list) and len(selected) == 0:
                self.logger.debug("No devices selected; returning empty list.")
                return []

            target_ids: List[str]
            if selected is None:
                target_ids = list(by_id.keys())
            else:
                target_ids = [d for d in selected if d in by_id]

            enriched: List[Dict[str, Any]] = []
            for did in target_ids:
                base = dict(by_id.get(did, {}))
                
                base.setdefault("id", did)
                base.setdefault("name", base.get("alias") or f"Cuby Device {did}")
                base.setdefault("status", base.get("status", "unknown"))

                state: Dict[str, Any] | None = None
                try:
                    state = await self._api.get_state(self._token, did)
                except CubyApiError as err:
                    # If /state/{id} fails, try full detail
                    self.logger.debug("get_state(%s) failed (%s), trying device_detail", did, err)
                    try:
                        detail = await self._api.get_device_detail(self._token, did)
                        
                        base["lastState"] = detail.get("lastState")
                        base["data"] = detail.get("data")
                    except Exception as err2:
                        self.logger.warning("Failed to fetch detail for %s: %s", did, err2)

                if state is not None:
                    base["lastState"] = state
                    base.setdefault("data", by_id.get(did, {}).get("data"))

                enriched.append(base)

            self.logger.debug("Enriched %s devices; sample=%s", len(enriched), enriched[0] if enriched else None)
            return enriched

        except CubyAuthError as err:
            raise UpdateFailed(f"Auth error: {err}") from err
        except CubyApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected: {err}") from err
