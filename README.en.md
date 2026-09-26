# EcoVolter for Home Assistant

[Čeština](README.md) | **English**

Custom Home Assistant integration for EcoVolter chargers using the local API.

> **Status:** early v0.1 test build. Test it locally before relying on it for unattended charging.

## Features

- Local communication; no cloud required
- Multiple EcoVolter chargers
- IP address or hostname during setup
- Cached hostname → IP resolution for fast API calls
- DNS refresh every hour and immediate re-resolution after a network failure
- Charging state and vehicle connection
- Current power and session energy
- Lifetime energy, charging count and charging time
- Per-phase current and voltage
- Enable/disable charging
- Enable/disable three-phase mode
- Set charging current from 6 to 16 A
- Czech and English Home Assistant UI

The integration uses the EcoVolter Local API endpoints for charger status, settings and diagnostics.

## Installation for testing

Copy:

`custom_components/ecovolter`

to:

`/config/custom_components/ecovolter`

Restart Home Assistant. Then open **Settings → Devices & services → Add integration** and search for **EcoVolter**.

Enter:

- the charger's IP address or hostname
- the Local API secret

**Never publish your API secret.** It is stored in the Home Assistant config entry, not in this repository.

## Hostname / DNS behaviour

When a hostname is configured, the integration resolves it and caches the resulting IP address. Normal API calls then go directly to that IP for faster communication.

The hostname is re-resolved every 60 minutes. If a request fails because of a network/connection error, the integration immediately resolves the hostname again and retries once. Authentication failures do not trigger DNS retries.

## Dashboard

See `examples/dashboard.yaml`.

Entity IDs depend on the name assigned by Home Assistant. Replace the example entity IDs with your actual IDs.

## Notes

EcoVolter and its local API are third-party products/services. This project is an independent Home Assistant integration and is not affiliated with the manufacturer.

Home Assistant automations are not a replacement for electrical protection or safety systems.

## License

MIT © 2026 IT síť s.r.o.
