# Security Policy

## Supported versions

Only the latest release of Felicity Solar Local receives security fixes. Please update to it before reporting an issue. The rolling `edge` prerelease is fixed on a best-effort basis, and older releases are not patched.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately through GitHub instead: go to the repository's **Security** tab and click **Report a vulnerability**, or open [a new advisory](https://github.com/fabiomatavelli/ha-felicity-solar-local/security/advisories/new) directly.

Include as much of the following as you can:

- The integration version and your Home Assistant version.
- A description of the issue and its impact.
- Steps to reproduce it, or a proof of concept.

Don't attach unredacted data from your own installation. The integration's **Download diagnostics** file already redacts the IP address and serial numbers, but double-check anything else you include (logs, raw payloads, screenshots) before sharing it.

## What to expect

This project is maintained by one person in their spare time, so responses are best-effort:

- You should get an acknowledgement within about 7 days.
- Once the issue is confirmed, the fix is developed in a private advisory and published as a new release, followed by the advisory itself.
- You'll be credited in the advisory unless you'd rather stay anonymous.

## Scope

In scope:

- The integration code in `custom_components/felicity_solar_local`, e.g. unsafe handling of a malicious or malformed payload from the TCP socket, the config flow, or diagnostics leaking data that should be redacted.
- The standalone `scripts/probe.py` tool.

Out of scope:

- The battery's own local protocol on TCP port `53970`. It has no authentication by the manufacturer's design, so anything on your network can query the battery directly; please report issues with the battery, its WiFi module or firmware to Felicity Solar.
- Felicity's cloud services and mobile apps.
- Home Assistant itself and HACS, which have their own security policies.

## Hardening tip

Because the battery accepts unauthenticated connections from any host that can reach it, consider placing it on an isolated network or VLAN and only allowing your Home Assistant host to reach port `53970`.
