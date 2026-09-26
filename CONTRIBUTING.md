# Contributing

Thanks for considering a contribution to Felicity Solar Local!

## Dev setup

```console
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-test.txt
```

`requirements-test.txt` is pinned to exact versions (not ranges) so everyone - local dev and
CI - runs the identical toolchain; a version drift between them is exactly what caused a
Linux-only CI failure that didn't reproduce locally once. Dependabot opens a PR to bump these
weekly; review and merge it like any other PR (it goes through the same required checks).

## Running checks

```console
ruff check .
pytest
```

Both must pass before a PR can be merged (enforced by CI - see `.github/workflows/test.yml`
and `validate.yml`, which also run `hassfest` and the HACS validation action).

## Adding a new battery model profile

If you'd rather not write the profile yourself, request it in an issue instead. With the
integration installed, attach its **Download diagnostics** file (serials and IP already
redacted) - Home Assistant shows a repair with a link to open the issue when the model isn't
recognized. Without it, `python3 scripts/probe.py --report <battery-ip>` generates a redacted
issue body. The [battery profile request form](https://github.com/fabiomatavelli/ha-felicity-solar-local/issues/new?template=battery_profile.yml)
takes the same data field by field, and the `request-battery-profile` agent skill in
`.agents/skills/` can walk you through either path and open the issue.

To add a profile yourself:

1. Capture a complete payload: the `raw_data` section of the integration's diagnostics
   download, or the JSON block from `python3 scripts/probe.py --report <your-battery-ip>`.
   Both have the serials redacted, so either can be committed as a test fixture. Note the
   `Type`/`SubType` it reports.
2. Compare its raw JSON shape to `tests/fixtures/sample_response.json`.
3. Add a new `BatteryProfile` in `custom_components/felicity_solar_local/profiles.py`,
   matched by your device's `Type`/`SubType`, and add it to the `PROFILES` tuple. Only mark
   `confidence="verified"` if you've cross-checked field scaling against another known-good
   source for that same battery (e.g. its cloud app, if it has one).
4. Add a corresponding test fixture and test cases in `tests/test_profiles.py`.

## Commit messages

This repo uses [Conventional Commits](https://www.conventionalcommits.org/) for every commit:

```
<type>[optional scope]: <description>
```

Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `ci`, `chore`. This is required, not
just a style preference - `release-please` parses commit history on `main` to decide the next
version number and changelog. A `BREAKING CHANGE:` footer triggers a major version bump.

`.github/workflows/commitlint.yml` enforces this automatically by checking that your PR title
follows Conventional Commits - it'll fail the check if it doesn't. If you squash-merge, GitHub
uses the PR title as the commit message on `main`, so a correctly formatted title is what
`release-please` actually sees.

## Release process

- Every push to `main` republishes a single rolling **`edge`** prerelease
  (`.github/workflows/edge-prerelease.yml`) - the `edge` tag is force-moved to the latest
  commit and its GitHub Release updated with a fresh zip, so there's always exactly one
  "latest main" build to install and test via HACS, rather than an ever-growing pile of
  per-PR tags that outlive their PRs.
- `release-please` (`.github/workflows/release-please.yml`) maintains a standing "Release PR"
  on `main` that aggregates unreleased Conventional Commits. Merging that PR bumps
  `manifest.json`'s version, tags the real release, and publishes it - no manual version
  bumping.

## Pull requests

Keep PRs focused. Include tests for behavior changes. If you're changing scaling/field mapping
in `profiles.py`, explain in the PR description how you verified the new values (what you
compared against) - that verification is what the `confidence` field on `BatteryProfile` is
meant to reflect honestly.
