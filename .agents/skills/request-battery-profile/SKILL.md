---
name: request-battery-profile
description: Collect a Felicity Solar battery's raw data and open (or draft) a GitHub issue asking for a new battery profile, without writing any code. Use when the user has a battery model that isn't recognized/verified yet and wants to request support instead of opening a PR.
---

# Request a new battery profile

Goal: turn the user's battery data into a complete, redacted "battery profile request" issue
on `fabiomatavelli/ha-felicity-solar-local`. The maintainer needs the **complete** raw
payload (every key - it becomes a test fixture) plus, ideally, vendor-app readings to
cross-check scaling. This is a request, not a contribution: don't edit `profiles.py` or any
other file in the repo.

## 1. Get the raw payload

Ask the user which source they have, preferring the first - most people asking already run
the integration (unrecognized models load on a generic profile), and it needs no extra tools:

- **A diagnostics file** downloaded from Home Assistant: **Settings** > **Devices &
  services** > **Felicity Solar Local** > the ⋮ menu of the battery's entry > **Download
  diagnostics**.
  Its `raw_data` object is the payload, already redacted; `device_type`/`device_subtype` at
  the top give the model codes, and `profile_matched: false` confirms it's on the generic
  profile. Build the body in the same format `scripts/probe.py --report` produces (see
  `render_report()` in that script) with `raw_data` as the payload. If the user has several
  packs of the same model, one file is enough for the body; mention the others in Notes.

- **Battery IP on their LAN**, if the integration isn't installed (needs Python 3 on a
  machine that can reach the battery):

  ```console
  python3 scripts/probe.py --report <battery-ip> --output <tmp-dir>/battery-report.md
  ```

  Stdlib-only, no Home Assistant needed. It prints and writes a Markdown issue body with
  `DevSN`/`wifiSN` already redacted. Use a temp directory outside the repo for the output.
  If it fails to connect: the battery must be on the same network, port `53970` reachable,
  and the device's TCP stack may only tolerate one client at a time - ask the user to
  temporarily disable the integration's config entry in Home Assistant if it's polling the
  battery.

Never ask the user to paste only "the relevant" fields - partial payloads are exactly what
stalled earlier requests.

## 2. Check it isn't already supported or requested

- Read `Type`/`SubType` from the payload and compare with the `type_code`/`subtype_code` of
  each profile in `PROFILES` (`custom_components/felicity_solar_local/profiles.py`). If a
  profile already matches, tell the user which one, and that updating the integration is
  the fix - don't open an issue. If it matches a *best-effort* profile, offer to open the
  issue anyway as a verification report with vendor-app readings (step 3).
- Look for an existing request:
  `gh issue list -R fabiomatavelli/ha-felicity-solar-local --state all --search "SubType=<n>"`.
  If one exists, point the user at it and suggest adding a comment there instead.

## 3. Fill in what the device can't report

Ask the user for:

- The exact model from the battery's label (e.g. `FLA48300`). Put it in the
  `### Battery model` section and in the title in place of `<model>`.
- If they have the Felicity app/cloud: SOC, pack voltage, current, temperature(s) and
  capacity, read at roughly the same moment as the payload. Fill the
  `### Vendor app readings` list; leave it empty rather than guessing.
- Anything odd they noticed (values that look wrong, firmware version, number of packs)
  for `### Notes`.

Remove the HTML `<!-- ... -->` placeholder comments once a section is filled in.

## 4. Privacy check

Before showing the final body, confirm it contains no IP address, hostname, MAC address,
serial number (`DevSN`/`wifiSN` values must read `**REDACTED**`) or other personal data.

## 5. Confirm, then publish

Show the user the final title and body and **ask for explicit confirmation** before
creating anything - opening an issue is public.

With confirmation, and if `gh auth status` succeeds:

```console
gh issue create -R fabiomatavelli/ha-felicity-solar-local \
  --title "[Battery profile] <model> (Type=<t>, SubType=<s>)" \
  --body-file <tmp-dir>/battery-report.md
```

Don't pass `--label` (it fails for users without triage access; the maintainer labels it).
Give the user the issue URL `gh` prints.

If `gh` isn't installed/authenticated, or the user prefers to post it themselves: give them
the final body to paste as-is into a blank issue, with the title prefilled - `probe.py
--report` prints that link on stderr, or build it as
`https://github.com/fabiomatavelli/ha-felicity-solar-local/issues/new?title=<url-encoded title>`.
Not the `battery_profile.yml` form: it splits the body into separate fields.

Delete the temp report file afterwards.
