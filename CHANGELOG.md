# Changelog

## v0.2.1 — 2026-09-29

- Added the Minimalistic card layout for a compact charger overview and control.
- Added selectable current control style for all card variants: slider or − / value / +.
- Added direct manual current input from 6–16 A.
- Improved plus/minus controls with immediate visual current updates.
- Improved manual input focus handling during 1-second Home Assistant state refreshes.
- Charging and three-phase controls now react optimistically without waiting for the next API state.
- Charger settings continue to be verified by the regular 60-second settings refresh.
- Improved layout and alignment of the compact current control.


## v0.2.0 — 2026-09-29

- Added dedicated EcoVolter Home Assistant card with Compact and Detailed layouts.
- Added Czech and English card UI and charger selection in the card editor.
- Added configured charging current from Local API settings.
- Added active-phase detection and per-phase current/voltage display.
- Improved current slider behaviour.
- Increased live status refresh rate to 1 second.
- Settings refresh separately every 60 seconds to avoid stale values overwriting recent changes.
- Serialized Local API requests to prevent overlapping GET/PATCH calls.
- Improved resilience to partial API failures while retaining last known good values.
- Improved hostname handling, DNS caching and Local API HMAC communication.
- Added native Lovelace examples for compact, detailed and dual-charger dashboards.

## v0.1.0

- Initial public release.
