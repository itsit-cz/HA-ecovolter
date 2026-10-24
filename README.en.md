# EcoVolter for Home Assistant

[Čeština](README.md) | **English**

Custom Home Assistant integration for EcoVolter chargers using the local API.

> **Current release:** v0.2.1. The integration communicates locally with EcoVolter and includes a dedicated Home Assistant card.

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
- Dedicated EcoVolter card: Minimalistic / Compact / Detailed, charger selection and CZ/EN
- Live telemetry refreshed every 2 seconds (configurable 1–60 s in the integration options)
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

If the charger stops responding, polling backs off (up to 30 s) so it can recover. After 60 s without a response, entities become unavailable instead of showing frozen values.

After updating, if the mobile Companion app still shows the old card, use *Settings → Companion app → Troubleshooting → Reset frontend cache* or restart the app.

The hostname is re-resolved every 60 minutes. If a request fails because of a network/connection error, the integration immediately resolves the hostname again and retries once. Authentication failures do not trigger DNS retries.

## EcoVolter card

The integration registers a dedicated **EcoVolter** card that can be added from the standard dashboard editor. The card editor lets you select a charger, choose **Minimalistic**, **Compact** or **Detailed**, set a custom name, and select **Čeština / English**.

The card shows power, session energy, active phases and configured charging current. It can enable/disable charging, switch between single/three-phase mode and set charging current from 6–16 A. The editor can use either a slider or compact **− / value / +** current control with manual input. The Minimalistic variant places essential data directly in the status line, while Detailed also shows L1–L3 currents, L1–L3 voltages and lifetime statistics.

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

## Charging scheduler

Choose a mode in the card (Scheduler section) or via entities: **Manual**, **Cheapest** (hours or kWh + *Ready by*; cheapest slots are selected and charging is switched automatically; optional max price), **Below limit** and **Low tariff only**. Prices come from a custom final-price sensor (list attribute `[{start, price, tariff}]`, auto-detected, used as-is) or from the [Czech Energy Spot Prices](https://github.com/rnovacek/homeassistant_cz_energy_spot_prices) sensor; set distribution prices (VT/NT) and VT windows in the integration options. Manual changes are respected until the plan changes its decision.
