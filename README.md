# 🔋 Felicity Solar Local for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Tests](https://github.com/fabiomatavelli/ha-felicity-solar-local/actions/workflows/test.yml/badge.svg)](https://github.com/fabiomatavelli/ha-felicity-solar-local/actions/workflows/test.yml)

A Home Assistant custom integration that reads Felicity Solar battery data **directly over
your local network** - no cloud account, no internet dependency. It talks to the battery's
onboard WiFi module using its local TCP/JSON protocol.

> Looking for the cloud-based integration instead (Shine/FSolar account, inverters + batteries)?
> See [`felicity_solar_hacs`](https://github.com/matheustavarestrindade/felicity_solar_hacs).

## ✨ Features

- **Local polling, no cloud**: connects straight to the battery's IP over TCP.
- **UI configuration**: add a battery by IP, no YAML required.
- **All battery data**: voltage, current, power, SOC, SOH, capacity, all 16 individual cell
  voltages, min/max cell voltage, temperatures, charge/discharge limits, fault/warning codes.
- **Nothing hidden**: an optional diagnostic "Raw data" sensor exposes the complete device
  payload as attributes, even fields not mapped to a dedicated sensor (off by default - see
  Configuration below).
- **Multi-model aware**: sensor field mapping is looked up per battery model (see
  [Battery model support](#-battery-model-support) below) instead of hardcoded to one model.

## 🛠️ Installation

Requires **Home Assistant 2026.3.0 or newer**.

### Method 1: HACS (Recommended)

This integration is in the default HACS store, so no custom repository is needed.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fabiomatavelli&repository=ha-felicity-solar-local&category=integration)

**One-click:** click the badge above (requires [My Home Assistant](https://www.home-assistant.io/integrations/my/) set up on your instance) and click **Download** in the dialog that opens.

**Manual steps:**

1. Open Home Assistant and go to **HACS**.
2. Search for **Felicity Solar Local** and click it.
3. Click **Download** in the bottom right.
4. **Restart Home Assistant**.

### Method 2: Manual

1. Download the latest release from this repository.
2. Copy the `custom_components/felicity_solar_local` folder into your Home Assistant
   `/config/custom_components/` directory.
3. **Restart Home Assistant**.

## ⚙️ Configuration

1. Find your battery's local IP address (check your router's DHCP leases).
2. In Home Assistant, go to **Settings** > **Devices & Services** > **+ Add Integration**.
3. Search for **Felicity Solar Local**.
4. Enter the battery's IP address (port defaults to `53970`).
5. Repeat for each additional battery - one config entry per battery/IP.

Update interval (default 5s) and the **Keep connection open** toggle (on by default) can be
changed afterwards from the integration's **Configure** button. The battery's TCP server
tolerates multiple queries on the same open connection, so by default the integration keeps
it open between polls instead of reconnecting every time - with automatic reconnect if it
ever drops, and OS-level TCP keepalive so a dropped connection is noticed between polls
rather than only on the next failed query. Disabling **Keep connection open** switches to
reconnecting on every poll and raises the minimum interval to 10s.

If you installed this integration before persistent connections became the default, your
existing config entry will pick up the new 5s/persistent defaults automatically the next
time it reloads (e.g. on a Home Assistant restart), unless you've already set the update
interval/**Keep connection open** explicitly via **Configure**.

The same **Configure** dialog also has an **Enable raw data sensor** toggle (off by default).
Its `extra_state_attributes` embed the entire raw device payload, and re-writing that on every
poll adds meaningful recorder/frontend overhead at the fast default interval - turn it on for
troubleshooting or when capturing data to contribute a new battery model profile, and back off
otherwise.

### Confirming your battery works before setting up the integration

Run the standalone probe script against your battery's IP to confirm it speaks the protocol
and see its raw data:

```console
python3 scripts/probe.py <battery-ip>
```

## 🔋 Battery model support

| Model | Type / SubType | Status | Notes |
|---|---|---|---|
| Felicity Solar FLB48314TG1-H | 112 / 7353 | ✅ Verified | Field scaling cross-checked live against the same battery's cloud API readings. See `profiles.py`. |
| Felicity Solar FLA24100 | 112 / 6100 | ✅ Verified | 24 V / 8-cell pack. Temperatures are sourced from `BtemList` and were cross-checked live against the vendor app; See `profiles.py`. |
| Other Felicity WiFi batteries | — | ⚠️ Untested (best-effort) | Same protocol assumed, falls back to a generic profile with unverified scaling. [Contribute a verified profile](CONTRIBUTING.md#adding-a-new-battery-model-profile) for your model. |

This integration was built and verified against a **Felicity Solar FLB48314TG1-H**
(`Type=112, SubType=7353`). Field names/scaling were cross-checked live against the same
battery's readings from Felicity's cloud API - see `custom_components/felicity_solar_local/profiles.py`
for the full mapping.

Other Felicity WiFi-battery models likely speak the same protocol (same command, port, and
JSON shape were originally reverse-engineered against a different model, the FLA48300), but
scaling/field meaning for models other than the FLB48314TG1-H is **not verified**. Unrecognized
models fall back to a best-effort generic profile with the same field names; enable the raw
data sensor (see Configuration above) to see the untouched payload regardless of profile.

**Have a different Felicity Solar WiFi battery?** Run `scripts/probe.py` against it, compare
the output to `tests/fixtures/sample_response.json`, and open a PR adding a new
`BatteryProfile` to `profiles.py` (see [CONTRIBUTING.md](CONTRIBUTING.md)) - matched by your
device's own `Type`/`SubType` codes so it doesn't affect other models.

## 📡 Protocol

Reverse-engineered from [`mxbode/Felicitysolar-FLA48300-WiFi-Readout`](https://github.com/mxbode/Felicitysolar-FLA48300-WiFi-Readout)
(credit to that project for documenting the command/port). That repository has no license and
is written in JavaScript; this integration is a fresh Python implementation based on the
observed protocol facts, not a port of its code. In short: plain TCP on port `53970`, send
`wifilocalMonitor:get dev real infor`, read the JSON reply up to its first `}`, then write a
single `.` byte back as an acknowledgement. The device tolerates repeated queries on the same
open connection, so with **Keep connection open** enabled (the default) the client reuses one
connection across polls, with OS-level TCP keepalive so a dropped connection is still noticed
between polls, transparently reconnecting if it goes stale, instead of reconnecting every time.

There's a second command, `wifilocalMonitor:get Date`, which returns the device's UTC offset
(`timeZMin`, in minutes - both test batteries reported `60`, i.e. UTC+1) alongside its own
copy of the current time. The main query's own `date` field carries no timezone, so this
command is queried once per coordinator lifetime (not every poll, since the offset only
changes across DST transitions) to correctly timezone-localize the **Device timestamp**
sensor. It's sent over the same connection as the main query when persistent, never a second
concurrent one - the device's embedded TCP stack may only tolerate one client at a time.

## 👨‍💻 Author

Created and maintained by **Fábio Matavelli** ([@fabiomatavelli](https://github.com/fabiomatavelli)).

Contributions welcome - see [CONTRIBUTING.md](CONTRIBUTING.md).
