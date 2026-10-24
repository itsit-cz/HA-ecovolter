# EcoVolter for Home Assistant

[Čeština](README.md) | **English**

Home Assistant integration for **EcoVolter** EV chargers. It talks to the charger **locally** through its Local API, with no cloud involved. It ships with its own dashboard card and a **price-based charging scheduler** that supports spot and fixed tariffs, HDO (ripple control) and up to 3 cars.

> **Version 1.0.0** is the first public release for testing. Feedback is welcome in [Issues](https://github.com/itsit-cz/HA-ecovolter/issues).

---

## Contents

1. [Features](#features)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Adding a charger – setup wizard](#adding-a-charger--setup-wizard)
5. [EcoVolter card](#ecovolter-card)
6. [Charging scheduler](#charging-scheduler)
7. [Cars](#cars)
8. [Entities](#entities)
9. [Automation examples](#automation-examples)
10. [Price and HDO sensor formats](#price-and-hdo-sensor-formats)
11. [Troubleshooting](#troubleshooting)
12. [Limitations and known issues](#limitations-and-known-issues)
13. [Development and tests](#development-and-tests)

---

## Features

**Charger**

- Local communication through the Local API (HMAC), no cloud
- Multiple chargers in one Home Assistant
- Connect by serial number, IP address or hostname
- Vehicle and charging state, power, session energy, total energy, charging count and time
- Per-phase current and voltage, number of active phases
- Enable or disable charging, switch between 1 and 3 phases, set the charging current from 6 to 16 A
- Reliable communication: a fresh connection for every request and back-off during outages. After 60 s without a response, entities become *unavailable* instead of showing frozen values.

**Charging scheduler**

- Modes: **Manual · Cheapest · Below limit · Low tariff only**
- Target in **hours**, **kWh** or **% of the car battery**
- **Ready by** deadline with a day picker: today, tomorrow or the day after
- Picks the cheapest slots, which may be scattered in 15-minute steps, with an optional maximum price
- Prices: **spot** (a final-price sensor, or spot + markup + distribution + VAT), **fixed two-rate**, **fixed single-rate**
- Low and high tariff: **ČEZ Distribuce** (7-day HDO schedule), another HDO sensor, or manually entered times
- Spot: takes into account that next-day prices are published around 14:00
- Once the target is reached, it does not start charging again on its own, not even after the car is unplugged and plugged back in
- A manual change takes priority, and any change to the plan takes control again immediately

**Cars**

- Up to 3 cars per charger: battery sensor, capacity, efficiency, plug sensor
- Automatic detection of the plugged-in car, with a separate target % for each car

**Card**

- Minimalistic / Compact / Detailed variants, Czech and English
- Car switch, scheduler section with a price timeline and a cost estimate
- Works on mobile and for non-admin users

---

## Requirements

- **Home Assistant 2025.3 or newer** (tested on 2026.2)
- An **EcoVolter** charger with the **Local API** enabled and its **secret**
- The charger and Home Assistant on the same network

For price-based scheduling, depending on your tariff:

- **spot:** a price sensor, such as the [Czech Energy Spot Prices](https://github.com/rnovacek/homeassistant_cz_energy_spot_prices) integration or your own final-price sensor,
- **ČEZ HDO:** the ČEZ HDO integration, whose *raw data* sensor is used (optional),
- **% target:** your car's integration with a battery level sensor (optional).

---

## Installation

### HACS (recommended)

1. **HACS → three dots → Custom repositories**
2. Repository `https://github.com/itsit-cz/HA-ecovolter`, type **Integration**
3. Search for **EcoVolter** and click **Download**
4. **Restart Home Assistant**

### Manual

Copy `custom_components/ecovolter` to `/config/custom_components/ecovolter` and restart Home Assistant.

### After every update

Restart Home Assistant and **reload the page in the browser** (Ctrl+Shift+R). In the mobile app use *Settings → Companion app → Troubleshooting → Reset frontend cache*. Otherwise an old version of the card may stay loaded.

---

## Adding a charger – setup wizard

**Settings → Devices & services → Add integration → EcoVolter**

```
1. Connection: serial number / IP / hostname + Local API secret
2. Which tariff do you have?
   ├─ Spot ── Do you have a sensor with the final price (incl. distribution and VAT)?
   │          ├─ Yes → choose the sensor
   │          │        └─ does it include VT/NT? → step 3 is skipped
   │          └─ No  → spot sensor + markup + distribution VT/NT + VAT
   ├─ Fixed two-rate → energy VT/NT + distribution VT/NT + VAT
   └─ Fixed single-rate → energy + distribution + VAT (no step 3)
3. Where do low and high tariff come from? ČEZ Distribuce · another HDO sensor · manual
4. Cars: 0–3
5. Summary: prices incl. VAT, today's NT windows, cars → Save
```

- **Prices are entered excluding VAT.** Final price = (spot or energy + markup + distribution) × (1 + VAT). Nothing is added to a final-price sensor.
- The wizard checks the sensors you choose and tells you right away if a sensor has no prices or schedule in a supported format.
- **Never publish your Local API secret.** It is stored only in the Home Assistant configuration.

### Changing settings

**Settings → Devices & services → EcoVolter → ⚙ Configure** opens a menu:

| Item | What it changes |
|---|---|
| Prices and tariff | tariff type and prices (same branches as the wizard) |
| Low and high tariff (VT/NT) | VT/NT source |
| Cars | number of cars and their settings |
| Refresh interval | how often the charger is read (1–60 s, 2 s recommended) |

Settings from 0.x versions are migrated automatically when you update.

---

## EcoVolter card

The integration adds its own card. **Edit dashboard → Add card → EcoVolter.**

Card editor options:

| Option | Description |
|---|---|
| Charger | which EcoVolter charger |
| Variant | **Minimalistic** (status in one line) · **Compact** · **Detailed** (adds phases L1–L3 and statistics) |
| Current control | slider, or − / value / + |
| Scheduler | Auto (hidden in Minimalistic) · Show · Hide |
| Language | Čeština / English |
| Name | empty = device name from the integration |

**What the card shows**

- overview: power, session energy, active phases, set current,
- **car switch** with battery level. If the integration cannot tell which car is plugged in, the card asks: *"Which car is plugged in?"*,
- **Charging** and **3 phases** buttons, current control,
- **Scheduler:** modes, target (Hours / kWh / %), ready by (day + time), max price, plan status and a **price timeline**. Planned slots are highlighted, estimated prices are hatched and VT is underlined in red. Tap a bar to see its time and price.

Dashboard examples built from native Home Assistant cards are in [`examples/`](examples/).

---

## Charging scheduler

The scheduler runs inside the integration, so it works without an open dashboard and survives restarts. After installation it is in **Manual** mode and does not switch anything.

### Modes

| Mode | What it does |
|---|---|
| **Manual** | the scheduler does not switch anything |
| **Cheapest** | charges the target in the cheapest slots before *Ready by*; an optional *Max price* excludes more expensive slots |
| **Below limit** | charges whenever the price is below *Max price* |
| **Low tariff only** | charges only during the low tariff (hidden for single-rate tariffs) |

### Target (Cheapest mode)

- **Hours:** charging time,
- **kWh:** energy, converted to time from the current power or from the set current and phases,
- **%:** the car's battery level, available only for a car with a battery sensor and capacity. Energy needed = (target − current %) × capacity / efficiency. Charging **stops immediately** once the target % is reached.

### Ready by

- **Today:** the nearest occurrence of the time, repeating daily. At 12:00 with 07:00 selected, this means tomorrow morning.
- **Tomorrow / Day after:** a fixed date that does not shift at midnight. Once it has passed, the scheduler goes back to the daily deadline.

### Behaviour

- **Next-day spot prices** are published around 14:00. If the deadline is beyond the known prices, the scheduler estimates the unknown part (the average of recent prices). It charges now only in slots cheaper than that estimate and plans the rest once the prices are published.
- **Target reached** means done: charging does not start on its own after unplugging and plugging in again, or after the deadline. A new plan starts with **Charge again**, by changing the target, deadline or mode, or when an automation sets the same value again.
- **A manual change** (the Charging button or the EcoVolter app) takes priority until the plan changes its own decision.
- **A change to the plan** in the card or through entities takes control and switches the charger **immediately**.
- **Plug-in:** the charger state is read right away. If the charger enables charging by itself, this is not treated as a manual change.
- If there is not enough time before the deadline, the card shows how much can be charged.

---

## Cars

In the wizard (or *Configure → Cars*) you can add **up to 3 cars**:

| Field | Description |
|---|---|
| Name | a unique name, shown in the card |
| Battery level sensor (%) | from the car's integration; enables % targets |
| Battery capacity (kWh) | **usable** capacity, required with a battery sensor |
| Charging efficiency (%) | charging losses, 90 % by default (typically 85–92 %) |
| Plug sensor | "cable connected", "charging" or charging state from the car's integration; enables detection |

**Automatic detection:** after the charger reports a car, the integration watches the cars' plug sensors for up to 2 minutes. If exactly one car reports plugged in, it is selected. Otherwise the card asks. A manual choice in the card always wins. States such as `on`, `connected`, `plugged` and `charging` count as plugged in.

- **Target %** is remembered separately for each car.
- **Other car:** a visitor or a car without sensors; the target is in hours or kWh only.
- If a different car is plugged in than the one whose target was reached, a new plan starts.

---

## Entities

Names follow the Home Assistant language. Entity IDs depend on the device name.

**Charger**

| Entity | Type | Notes |
|---|---|---|
| Vehicle connected | binary_sensor | |
| Charging | binary_sensor | charging right now |
| Power | sensor (kW) | |
| Session energy | sensor (kWh) | energy of the current session |
| Total energy | sensor (kWh) | lifetime counter, for statistics and the Energy dashboard |
| Charging count, Total charging time | sensor | statistics |
| Current L1–L3, Voltage L1–L3 | sensor | |
| Active phases | sensor | phases above 1 A |
| Set current | sensor (A) | current set in the charger |
| Charging enabled | switch | |
| Three-phase charging | switch | |
| Charging current | number (6–16 A) | |

**Scheduler**

| Entity | Type | Values |
|---|---|---|
| Charging mode | select | `manual`, `cheapest`, `price_limit`, `low_tariff` |
| Charging target | select | `hours`, `energy`, `soc` |
| Charging hours | number (h) | |
| Charging energy | number (kWh) | |
| Charge to | number (%) | for the selected car |
| Max price | number (CZK/kWh) | 0 = no limit |
| Ready by | time | |
| Ready day | select | `today`, `tomorrow`, `day_after` |
| Car | select | car names + `other` (only when cars are configured) |
| Charge again | button | starts a new plan after the target was reached |
| Next planned charging | sensor (timestamp) | the full plan, cost estimate and car state in attributes |
| Scheduled charging now | binary_sensor | attribute `reason` |
| Electricity price incl. distribution | sensor (CZK/kWh) | current price incl. VAT |

---

## Automation examples

**Every evening, plan charging to 80 % by 6:30**

```yaml
alias: EcoVolter – overnight charging
triggers:
  - trigger: time
    at: "18:00:00"
actions:
  - action: select.select_option
    target: { entity_id: select.ecovolter_charging_target }
    data: { option: soc }
  - action: number.set_value
    target: { entity_id: number.ecovolter_charge_to }
    data: { value: 80 }
  - action: time.set_value
    target: { entity_id: time.ecovolter_ready_by }
    data: { time: "06:30:00" }
  - action: select.select_option
    target: { entity_id: select.ecovolter_charging_mode }
    data: { option: cheapest }
```

Setting the same value starts a new plan even after the previous one was completed, so this works as a daily routine.

**Notify when the car won't be charged in time**

```yaml
alias: EcoVolter – not in time
triggers:
  - trigger: template
    value_template: >
      {{ state_attr('sensor.ecovolter_next_planned_charging', 'complete') == false
         and states('select.ecovolter_charging_mode') == 'cheapest' }}
actions:
  - action: notify.notify
    data:
      message: "The car won't be charged by the deadline."
```

Replace the entity IDs (`select.ecovolter_…`) with your own.

---

## Price and HDO sensor formats

**Final-price sensor:** an attribute with a list of slots. `price` is the final price per kWh, `tariff` is optional, and `spot` is used when you choose "no final price".

```yaml
prices:
  - start: '2026-10-24T21:00:00+02:00'
    price: 4.7002
    spot: 3.478
    tariff: NT
```

**Czech Energy Spot Prices:** attributes `time → price`. Hourly and 15-minute prices work, and CZK/kWh or CZK/MWh is detected automatically.

**ČEZ HDO raw data:** attribute `raw_json` with entries `datum` (`24.10.2026`) and `casy` (`00:00-08:00; 09:00-12:00; …`). `casy` lists the **low tariff** windows.

**Other HDO sensor:** a binary sensor (on = NT), or an attribute with a list of `{start, end}` NT windows.

**Manual VT times:** `8:00-9:00, 12:00-13:00, 16:00-17:00, 19:00-20:00`. Windows across midnight are allowed (`22:00-02:00`).

---

## Troubleshooting

| Problem | Fix |
|---|---|
| *Custom element doesn't exist: ecovolter-card* | reload the page (Ctrl+Shift+R); in the app use *Reset frontend cache* |
| Entities are *unavailable* | the charger has not responded for 60 s; check the network and IP. The integration recovers on its own. |
| Values update slowly | during outages polling slows down to up to 30 s and returns to normal once the charger responds |
| The scheduler does not charge | check the plan status in the card, or the `reason` attribute of *Scheduled charging now* (`manual`, `waiting`, `no_prices`, `no_soc`, `target_reached` …) |
| % target not available | the selected car has no battery sensor or capacity |
| The car is not detected | set a plug sensor for the car and check which state it reports (`on`, `connected`, `charging` …) |

**Debug log:** add this to `configuration.yaml`

```yaml
logger:
  logs:
    custom_components.ecovolter: debug
```

---

## Limitations and known issues

- Tested with EcoVolter II, spot prices and ČEZ Distribuce. Other distributors (EG.D, PRE) are supported through a generic HDO sensor or manual times.
- kWh targets are converted to time from the charging power, so they are estimates.
- Battery capacity and efficiency are up to you. Fine-tune the efficiency for more accurate % targets.
- Car detection depends on what the car's integration provides.
- Home Assistant automations do not replace circuit breakers or other electrical safety devices.

---

## Development and tests

```bash
pip install pytest-homeassistant-custom-component
pytest tests
```

Report bugs and ideas in [Issues](https://github.com/itsit-cz/HA-ecovolter/issues). See [CHANGELOG.md](CHANGELOG.md) for changes.

EcoVolter and its Local API are third-party products. This project is an independent integration and is not affiliated with the manufacturer.

## License

MIT © 2026 IT síť s.r.o.
