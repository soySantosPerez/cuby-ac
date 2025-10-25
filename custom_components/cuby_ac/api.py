from __future__ import annotations

from typing import Any, Dict, List, Optional
from aiohttp import ClientSession, ClientTimeout

TOKEN_TTL_SECONDS = 365 * 24 * 60 * 60  # A Year / 365 days
DEFAULT_TIMEOUT = 15  # seconds


class CubyAuthError(Exception):
    """Raised when authentication fails or token is invalid."""


class CubyApiError(Exception):
    """Raised for unexpected API errors."""


class CubyApi:
    """Cuby HTTP client using HA's aiohttp session."""

    def __init__(self, session: ClientSession, base_url: str = "https://cuby.cloud/api/v2") -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._timeout = ClientTimeout(total=DEFAULT_TIMEOUT)

    # ----------------------
    # Auth / Token
    # ----------------------
    async def get_token(self, username: str, password: str, ttl_seconds: int = TOKEN_TTL_SECONDS) -> Dict[str, Any]:
        """
        Request an access token for the given user.
        POST /token/{username} body: {"password": "...", "expiration": <seconds>}
        """
        url = f"{self._base_url}/token/{username}"
        payload = {"password": password, "expiration": ttl_seconds}

        async with self._session.post(url, json=payload, timeout=self._timeout) as resp:
            if resp.status == 401:
                raise CubyAuthError("Invalid credentials.")
            if resp.status >= 400:
                text = await resp.text()
                raise CubyApiError(f"API {resp.status}: {text}")
            data = await resp.json()

        token = data.get("token") or data.get("access_token")
        if not token:
            raise CubyApiError("Token not found in response.")
        return {"token": token, "raw": data, "expires_in": ttl_seconds}

    def _auth_headers(self, token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # ----------------------
    # Devices
    # ----------------------
    async def get_devices(self, token: str) -> List[Dict[str, Any]]:
        """
        List all devices linked to the account.
        GET /devices -> [ { id, name, status, data{ temperature, humidity, rssi, ...}, ... }, ... ]
        https://cuby.cloud/cuby/docs/api/v2/#/default/get_devices
        """
        url = f"{self._base_url}/devices"
        async with self._session.get(url, headers=self._auth_headers(token), timeout=self._timeout) as resp:
            if resp.status == 401:
                raise CubyAuthError("Token expired or invalid.")
            if resp.status >= 400:
                text = await resp.text()
                raise CubyApiError(f"API {resp.status}: {text}")
            data = await resp.json()

        return data if isinstance(data, list) else data.get("devices", [])

    async def get_device_detail(self, token: str, device_id: str) -> Dict[str, Any]:
        """
        Return device detail including lastState and data.
        GET /devices/{id}?getState=true
        https://cuby.cloud/cuby/docs/api/v2/#/default/get_devices__deviceID_
        """
        url = f"{self._base_url}/devices/{device_id}"
        params = {"getState": "true"}

        async with self._session.get(url, headers=self._auth_headers(token), params=params, timeout=self._timeout) as resp:
            if resp.status == 401:
                raise CubyAuthError("Token expired or invalid.")
            if resp.status >= 400:
                text = await resp.text()
                raise CubyApiError(f"API {resp.status}: {text}")
            data = await resp.json()

        if not isinstance(data, dict):
            raise CubyApiError(f"Invalid device detail for {device_id}: {data}")
        return data

    # ----------------------
    # State (read / write)
    # ----------------------
    async def get_state(self, token: str, device_id: str) -> Dict[str, Any]:
        """
        Return current AC state (same structure you showed under lastState).
        GET /state/{id}
        https://cuby.cloud/cuby/docs/api/v2/#/default/get_state__deviceID_
        """
        url = f"{self._base_url}/state/{device_id}"
        async with self._session.get(url, headers=self._auth_headers(token), timeout=self._timeout) as resp:
            if resp.status == 401:
                raise CubyAuthError("Token expired or invalid.")
            if resp.status >= 400:
                text = await resp.text()
                raise CubyApiError(f"API {resp.status}: {text}")
            data = await resp.json()

        if not isinstance(data, dict):
            raise CubyApiError(f"Invalid state for {device_id}: {data}")
        return data

    async def set_state(self, token: str, device_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a control command to the device.
        POST /state/{id}
        Required 'type' in payload: one of ["power","mode","fan","temperature","verticalVane","horizontalVane","display","turbo","long","eco"]
        Example payloads:
          {"type":"power","power":"on"}
          {"type":"mode","mode":"cool"}
          {"type":"temperature","temperature":23}
          {"type":"fan","fan":"auto"}
        https://cuby.cloud/cuby/docs/api/v2/#/default/post_state__deviceID_
        """
        if "type" not in payload or not isinstance(payload["type"], str):
            raise ValueError("Payload must include a 'type' key (string).")

        url = f"{self._base_url}/state/{device_id}"
        async with self._session.post(url, headers=self._auth_headers(token), json=payload, timeout=self._timeout) as resp:
            if resp.status == 401:
                raise CubyAuthError("Token expired or invalid.")
            if resp.status >= 400:
                text = await resp.text()
                raise CubyApiError(f"API {resp.status}: {text}")
            data = await resp.json()

        return data
