# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this repo is

A Home Assistant HACS integration (`custom_components/felicity_solar_local`) that polls
Felicity Solar batteries over a local TCP/JSON protocol (port `53970`). See `README.md` for
the protocol summary and `custom_components/felicity_solar_local/profiles.py` for the
verified field mapping/scaling - that file's module docstring and the live-validation notes
in `README.md` are the source of truth for what each device field means. Don't re-derive
scaling from guesswork; if a field's meaning isn't already documented there, treat it as
unverified and route it through the raw-data diagnostic sensor rather than inventing a scale.

## Commit style

Every commit, in this repo without exception, uses **Conventional Commits**:
`<type>[optional scope]: <description>` (e.g. `feat(sensor): add cell temperature sensors`,
`fix(api): handle null Batt[2][0] from firmware`). This isn't optional formatting - it's what
`release-please` (`.github/workflows/release-please.yml`) parses to compute version bumps and
changelogs. A `fix:` commit bumps patch, `feat:` bumps minor, a `BREAKING CHANGE:` footer
bumps major.

## Workflow

Never commit or push directly to `main`. Create a branch and open a PR (`gh pr create`) so the
maintainer can review before merging - even for changes that are already tested and CI-green.
This is also what the repo's CI is built around: `edge-prerelease.yml` republishes a single
rolling `edge` prerelease on every push to `main` (not per-PR, to avoid an ever-growing pile
of stale tags), and `commitlint.yml` checks the PR title against Conventional Commits (which matters
since a squash-merge uses the PR title as the commit `release-please` sees on `main`).

## Before committing

- `ruff check .` must pass.
- `pytest` must pass (`pip install -r requirements-test.txt` first).
- Never commit real LAN IP addresses, hostnames, or credentials. Tests and fixtures use
  `tests/fixtures/sample_response.json` (a real but non-identifying device payload) and
  placeholder IPs like `192.168.1.50` - not anyone's actual network.

## Adding support for a new battery model

Don't modify `FLB48314TG1H_PROFILE`'s scaling to "probably also work" for another model.
Instead add a new `BatteryProfile` to `PROFILES` in `profiles.py`, matched by that model's own
`Type`/`SubType` codes, with `confidence="verified"` only once its fields have actually been
cross-checked (e.g. against that model's cloud-reported values, the way FLB48314TG1-H was).
`coordinator.py` and `sensor.py` need no changes for this - `select_profile()` is the only
dispatch point.

## Requesting a new battery profile (no code)

If the user wants support for their battery model but doesn't want to write the profile themselves, don't open a PR - help them open a "battery profile request" issue instead, by following `.agents/skills/request-battery-profile/SKILL.md` (read it directly if your agent doesn't load skills automatically). In short: get the complete payload from the integration's diagnostics download (preferred - no extra tooling, already redacted) or `python3 scripts/probe.py --report <ip>`, check the model isn't already in `PROFILES`, fill in the model name and vendor-app readings, and only run `gh issue create` after the user confirms the final body.

## Architecture pointers

- `api.py` - the TCP client only. No Home Assistant imports; keep it that way so
  `scripts/probe.py` can stay a standalone stdlib script mirroring the same protocol logic.
- `profiles.py` - field mapping/scaling per model. No I/O.
- `coordinator.py` - one `FelicityLocalCoordinator` per config entry (= one battery).
- `sensor.py` - builds entities from `coordinator.data.profile.sensors`, plus one always-on
  raw-data diagnostic sensor.
