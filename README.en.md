# EcoVolter for Home Assistant

[Čeština](README.md) | **English**

Custom Home Assistant integration for EcoVolter chargers using the local API.

> **Current release:** v0.2.0. The integration communicates locally with EcoVolter and includes a dedicated Home Assistant card.

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
- Dedicated EcoVolter card: Compact / Detailed, charger selection and CZ/EN
- Live telemetry refreshed every 1 second
- Charger settings read separately and controlled through PATCH
- Serialized API requests for more reliable communication

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

## EcoVolter card

The integration registers a dedicated **EcoVolter** card that can be added from the standard dashboard editor. The card editor lets you select a charger, choose **Compact** or **Detailed**, set a custom name, and select **Čeština / English**.

The card shows power, session energy, active phases and configured charging current. It can enable/disable charging, switch between single/three-phase mode and set charging current from 6–16 A. The Detailed variant also shows L1–L3 currents, L1–L3 voltages and lifetime statistics.

## Dashboard examples

Three ready-to-use native Home Assistant card examples are also included:

- `examples/lovelace/compact.yaml` – compact everyday control
- `examples/lovelace/detailed.yaml` – detailed view with phases and statistics
- `examples/lovelace/dual-charger.yaml` – overview for two chargers

Entity IDs depend on the name assigned by Home Assistant. Replace the example entity IDs with your actual IDs.

## Notes

EcoVolter and its local API are third-party products/services. This project is an independent Home Assistant integration and is not affiliated with the manufacturer.

Home Assistant automations are not a replacement for electrical protection or safety systems.

## License

MIT © 2026 IT síť s.r.o.
