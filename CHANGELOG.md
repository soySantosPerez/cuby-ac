# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2025-10-24
### Added
- Initial public release of **Cuby AC** integration for Home Assistant (API v2).
- Config Flow (UI): login with email + password; token stored for 365 days.
- Options Flow (UI): device selection and temperature unit preference (Follow device / °C / °F).
- Cloud polling via DataUpdateCoordinator; device registry integration.
- Climate entity: power on/off, HVAC mode (auto/cool/heat/dry/fan), target temperature.
- Unit conversion between device units and UI preference.
- Basic error handling and debug logging.

### Known limitations
- Fan speed presets and extra features (eco, turbo, display, long) not yet exposed.
- No diagnostics panel yet.
- No CI or unit test coverage thresholds yet.