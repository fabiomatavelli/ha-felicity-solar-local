# Changelog

## [0.5.2](https://github.com/fabiomatavelli/ha-felicity-solar-local/compare/v0.5.1...v0.5.2) (2026-08-29)


### Bug Fixes

* **diagnostics:** redact device serial from parsed_data ([#33](https://github.com/fabiomatavelli/ha-felicity-solar-local/issues/33)) ([91f816d](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/91f816d5ac4d79edc29cf18beec8a8d9efe08459))

## [0.5.1](https://github.com/fabiomatavelli/ha-felicity-solar-local/compare/v0.5.0...v0.5.1) (2026-07-23)


### Bug Fixes

* **ci:** drop unneeded brands ignore from hacs validation ([#22](https://github.com/fabiomatavelli/ha-felicity-solar-local/issues/22)) ([8382189](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/83821892a16fad2e94683bd91f02e3024814e505))

## [0.5.0](https://github.com/fabiomatavelli/ha-felicity-solar-local/compare/v0.4.0...v0.5.0) (2026-07-22)


### Features

* **profiles:** add verified FLA24100 (Type=112, SubType=6100) profile ([#20](https://github.com/fabiomatavelli/ha-felicity-solar-local/issues/20)) ([78687e0](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/78687e0f1e6fa7bce858294cecbdb5925bdccf40))

## [0.4.0](https://github.com/fabiomatavelli/ha-felicity-solar-local/compare/v0.3.0...v0.4.0) (2026-07-15)


### Features

* **coordinator:** invert current/power sign to match HA battery convention ([#18](https://github.com/fabiomatavelli/ha-felicity-solar-local/issues/18)) ([14a5d58](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/14a5d58642f15e85083f7e8ed64df29010219826))
* **sensor:** add aggregated max/min battery temperature sensors ([#16](https://github.com/fabiomatavelli/ha-felicity-solar-local/issues/16)) ([65db195](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/65db195a4b8ea2be4dfd25c225e37830ff34290e))

## [0.3.0](https://github.com/fabiomatavelli/ha-felicity-solar-local/compare/v0.2.1...v0.3.0) (2026-07-13)


### Features

* **sensor:** add device timestamp sensor with correct timezone ([#10](https://github.com/fabiomatavelli/ha-felicity-solar-local/issues/10)) ([5424fd7](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/5424fd7cda5ba053b6432bff91f77ca0ee6e91dc))
* **sensor:** make the raw data sensor opt-in, off by default ([#8](https://github.com/fabiomatavelli/ha-felicity-solar-local/issues/8)) ([500d5d0](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/500d5d00129fae6a741af0cf0b4425b44f909701))

## [0.2.1](https://github.com/fabiomatavelli/ha-felicity-solar-local/compare/v0.2.0...v0.2.1) (2026-07-12)


### Bug Fixes

* use literal state text instead of [%key:%] references ([32fc3d3](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/32fc3d3817a645064c6cdbe3bc400ca3eb3de9e2))
* use literal state text instead of [%key:%] references ([9591f25](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/9591f252f5faa3a69e7d82e017c5aec09e18b3e1))

## [0.2.0](https://github.com/fabiomatavelli/ha-felicity-solar-local/compare/v0.1.0...v0.2.0) (2026-07-12)


### Features

* **api:** add configurable persistent TCP connection ([d586459](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/d5864595fe34dc5ab74a951bbf1eb473b184f428))
* default to a persistent connection with faster polling and OS keepalive ([b6bb290](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/b6bb29070d1617e8c511650c4dea9134c32ddbf1))
* default to a persistent connection with faster polling and OS keepalive ([ec9f23f](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/ec9f23fc6b2a265d5f9e80f54725997f9829de4f))
* **profiles:** add charging_state enum sensor decoded from Bstate ([83c1b35](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/83c1b35d4895cc86e1d89d6820c60b6d7c6f83b8))
* **profiles:** add charging_state enum sensor decoded from Bstate ([5728529](https://github.com/fabiomatavelli/ha-felicity-solar-local/commit/572852920810264bda301ca396f3a8d1de3b268b))

## 0.1.0 (2026-07-12)


### Features

* add integration brand icon and tested-models table ([c77319e](https://github.com/fabiomatavelli/felicity_solar_local_hacs/commit/c77319ebe9b9223b5ec5652963cba37854e95c8d))
* initial Felicity Solar Local integration ([70513bb](https://github.com/fabiomatavelli/felicity_solar_local_hacs/commit/70513bb21ab8970aa40ce2b56a3c3233222580cf))


### Bug Fixes

* correct CI validation failures ([8e97829](https://github.com/fabiomatavelli/felicity_solar_local_hacs/commit/8e97829299f3f442f2c3c0284b3dc103c74913c4))
* force initial release to 0.1.0 instead of release-please's default 1.0.0 ([4777377](https://github.com/fabiomatavelli/felicity_solar_local_hacs/commit/4777377abd20ab1a4e070091699ab22ebb749446))
* seed release-please manifest at 0.0.0 instead of 0.1.0 ([9d242be](https://github.com/fabiomatavelli/felicity_solar_local_hacs/commit/9d242be0fb2212e012c241823293d6e2145e8641))
* **test:** drop flaky Python 3.12 CI job and fix connection-refused test ([49f33bc](https://github.com/fabiomatavelli/felicity_solar_local_hacs/commit/49f33bc5d242a16e04560a08ef0657845fdf00e8))
