# Changelog

## v0.4.0 — 2026-10-24

Charging scheduler.

- New modes: Manual, Cheapest hours, Below price limit, Low tariff (NT) only.
- Cheapest hours: set hours or kWh and a "ready by" time; the cheapest (possibly scattered) price slots before the deadline are selected and charging is switched on/off automatically. Re-plans when tomorrow's prices are published (around 14:00); until then the unknown part is estimated and only slots cheaper than the estimate are used.
- Price = spot price (Czech Energy Spot Prices, hourly or 15-min) + distribution VT/NT; VT windows and distribution prices are set in the integration options.
- Supports a custom final-price sensor (list attribute `[{start, price, tariff}]`, auto-detected); distribution is not added to it.
- Optional max price also limits the Cheapest hours plan.
- Manual changes (HA switch, EcoVolter app) are respected until the plan changes its decision.
- Charged time/energy is tracked per cycle; settings and progress survive restarts.
- New entities: charging mode, charging target, hours, energy, max price, ready by, next planned charging (with full plan), electricity price incl. distribution, scheduled charging now.
- Price type chosen during setup: spot / price sensor or fixed two-rate tariff (energy + distribution VT/NT). Setup and options are a guided multi-step flow.
- HDO: low-tariff windows from an HDO sensor (list of start/end, e.g. ČEZ distribuce `next_windows`) or a binary sensor; VT times as fallback.
- Charging target in % of the car battery (car SoC sensor, battery capacity, charging efficiency); stops as soon as the target % is reached.
- Any change of the plan (mode, target, deadline, max price) takes control immediately – overrides a manual change and the command rate limit.
- Target reached = done: no new charging after unplug/replug or past the deadline until a new target/deadline/mode is set or "Charge again" is pressed (new button entity, button in the card).
- Plug-in: charger settings are read immediately and a charger re-enabling itself is not treated as a manual override.
- "Ready by" day: Today (nearest, repeats daily), Tomorrow, Day after tomorrow (new select entity, day picker in the card).
- Card: "Ready by" uses hour/minute pickers (24 h) – the native time input sent half-typed times and was unreliable in the Companion app.
- Card: scheduler section with mode buttons, target/deadline/limit fields, price timeline with planned slots and cost estimate. Decimal comma accepted.

## v0.3.0 — 2026-10-24

Stability and mobile fixes.

Integration
- Fixed periodic freezes: every request now uses a fresh connection (`Connection: close`); the charger's web server hung on reused keep-alive sockets.
- Timeouts are no longer retried against the same IP (a hang used to block all other requests for up to 8 s).
- Garbled or truncated JSON responses are handled instead of failing the whole refresh.
- When the charger stops responding, polling backs off up to 30 s and settings/diagnostic reads are skipped so the charger can recover.
- After 60 s without a successful status read, entities become unavailable instead of showing frozen values.
- Default refresh interval changed from 1 s to 2 s; configurable 1–60 s in the integration options.
- Settings are verified 10 s after a write (previously up to 60 s).
- Failed writes show a clear error in Home Assistant.
- Card URL is cache-busted by file content so browsers and the Companion app load the new card.

Card
- Card no longer rebuilds its whole DOM on every Home Assistant update; taps on mobile were lost and the slider jumped back.
- Works for non-admin users (entities are found via `hass.entities` instead of the admin-only registry API).
- Styles are isolated in Shadow DOM and no longer leak into other dashboard cards.
- Optimistic switch/current values expire after 15 s if the charger does not confirm them.
- + / − taps are debounced into a single request.
- Shows "charger unavailable" and disables controls when the charger is offline.
- Failed commands revert the control and show a notification.
- HTML in device/card names is escaped.

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
