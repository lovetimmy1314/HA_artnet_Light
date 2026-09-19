# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Home Assistant custom integration `artnet_light` (HACS, targets the latest HA only — min 2026.9, D-015; Python ≥3.14 at runtime): discovers Art-Net nodes, and lets users add DMX fixtures (dimmer/CCT/RGB/RGBW/RGBWW) entirely through the config flow and options flow UI. User-facing docs are in Chinese; code/comments in English.

## Workflow (solo developer, agent-driven)

- **Start of a task**: read `Plan.md` (goals, progress, TODO) and `DECISIONS.md` (why things are the way they are). Don't re-litigate a recorded decision silently — if a change contradicts one, say so and ask.
- **During/after a task**:
  - Update the checkboxes / TODO list in `Plan.md` and its "最近更新" date.
  - Any non-obvious design choice (API shape, trade-off, rejected alternative, platform constraint) gets a new `D-NNN` entry appended to `DECISIONS.md` (背景 → 决定 → 理由/代价). Superseded entries are marked 「已废弃 → D-xxx」, never deleted.
- Report honestly which verification actually ran (local core tests vs. untested HA code) — much of the HA-side code can't be executed on the dev machine.

## Versioning & commits (mandatory, do it automatically without asking — DECISIONS D-010)

Every completed code change is committed and tagged by the agent at the end of the task:

1. Bump the version (SemVer): **patch** = fix/refactor/internal, **minor** = new feature or new option, **major** = breaking change to stored config (needs a config-entry migration).
2. Update the version in `custom_components/artnet_light/manifest.json` (the single source of truth; must equal the tag).
3. Add a section to `CHANGELOG.md` and tick/update `Plan.md` (and `DECISIONS.md` if applicable).
4. Run `python -m pytest tests/test_core.py -q -p no:homeassistant` first (and the HA tests on the Linux box when HA-layer code changed); don't tag a red build.
5. One commit, Conventional Commits prefix (`feat:` / `fix:` / `refactor:` / `test:` / `docs:` / `chore:`), then an annotated tag: `git tag -a vX.Y.Z -m "vX.Y.Z: <summary>"`.

Doc-only changes (Plan/DECISIONS/README/CLAUDE.md) are committed with `docs:` but **not** version-bumped or tagged. Work on `main` directly (solo repo). Never push or create remotes/releases without asking. The GitHub remote is named `HA_artnet_Light` (not `origin`): `git@github.com:lovetimmy1314/HA_artnet_Light.git`.

## Commands

Dev machine is Windows with only Python 3.11 (no Docker, no HA install). The `python` on PATH (Espressif's) has no pytest; if no scratch venv exists, run the core tests in the same Linux container as the HA tests (separate invocation). HA tests run on the Linux box `root@192.168.1.167` (see user-level CLAUDE.md) in throwaway containers.

Core tests and HA tests **must be separate pytest invocations**: the HA pytest plugin blocks sockets and replaces the event loop, which breaks the controller tests. `pytest.ini` therefore only collects `tests/ha`.

```bash
# HA-independent core tests (protocol, fixture math, UDP sender) — runs locally
python -m pytest tests/test_core.py -q -p no:homeassistant
python -m pytest tests/test_core.py -q -p no:homeassistant -k cct     # single test / subset

# HA flow tests on the Linux box. py3.14 resolves the same HA as production (2026.9.x); older Pythons cap at older HA — don't use them.
tar --exclude=.git --exclude=__pycache__ -cf - . | ssh -o BatchMode=yes root@192.168.1.167 \
  'rm -rf /root/work/HA_artnet_Light && mkdir -p /root/work/HA_artnet_Light && tar -x -C /root/work/HA_artnet_Light'
ssh -o BatchMode=yes root@192.168.1.167 'cd /root/work/HA_artnet_Light && docker run --rm --network host \
  -v $PWD:/src -v /root/work/.pipcache:/root/.cache/pip -w /src python:3.14 \
  sh -c "pip install -q -r requirements_test.txt >/dev/null 2>&1; python -m pytest -q tests/ha"'

# Fake Art-Net node: answers ArtPoll, prints received DMX (run on a LAN machine other than the HA host; both need UDP 6454)
python tools/fake_node.py --name TestNode --universes 0 1
```

`--network host` is required on the Linux box: Docker injects `HTTP(S)_PROXY=http://127.0.0.1:20171` (v2raya on the host), unreachable from a bridged container. The live HA container there is `1Panel-home-assistant-oGES` (HA 2026.9.2, host network, config at `/opt/1panel/apps/home-assistant/home-assistant/data`). Restarting it interrupts the user's home automations: ask before each deploy/restart.

End-to-end (after the user OKs a restart):
```bash
tar --exclude=__pycache__ -C custom_components -cf - artnet_light | ssh -o BatchMode=yes root@192.168.1.167 \
  'D=/opt/1panel/apps/home-assistant/home-assistant/data/custom_components; rm -rf $D/artnet_light && tar -x -C $D && docker restart 1Panel-home-assistant-oGES'
```
Drive flows/services through the HA REST API (`/api/config/config_entries/flow`, `/api/config/config_entries/options/flow`, `/api/services/light/...`) with the token in `/root/.ha_token` on the server (never print it; the local copy `HAkey.md` is git-ignored). Run `tools/fake_node.py` on this Windows machine (192.168.1.136) to receive DMX. Git Bash needs `MSYS_NO_PATHCONV=1` so `/api/...` arguments aren't rewritten into Windows paths.

CI (`.github/workflows/validate.yml`): hassfest, HACS validation, both pytest runs on Ubuntu/Py3.14 (latest HA).

## Architecture

Two layers, strictly separated (DECISIONS D-009):

- **Pure core (stdlib only, no `homeassistant` imports)**: `const.py`, `artnet.py` (packet build/parse), `fixture.py` (fixture model + level math), `controller.py` (per-node UDP socket, 512-byte buffers per universe, send loop, fades). `tests/test_core.py` and `tools/fake_node.py` load these via a stub package `artnet_core` to bypass `__init__.py`; adding an HA import to any of them breaks local testing. Use relative imports only between core modules.
- **HA layer**: `__init__.py`, `config_flow.py`, `discovery.py`, `light.py`.

Data flow for a light command: `ArtNetLight.async_turn_on` → `Fixture.compute_levels()` (floats 0–1 per channel letter, min/max output applied, `T` exempt) → `ArtNetController.apply()` (optional fade interpolates floats) → `Fixture.encode()` (8/16-bit bytes) → `set_channels()` marks universe dirty → send loop emits ArtDmx.

Key cross-file facts:
- **Storage**: one config entry per node. `entry.data` = host/port/name/mac/universes; `entry.options` = send settings + `fixtures` (list of `Fixture.to_dict()`). Fixture `id` (uuid) is the entity unique_id and the device identifier.
- **Live updates**: the options flow is an `OptionsFlowWithReload`, so any options change reloads the entry (no update listener; HA reports one as deprecated when a flow reloads the entry, D-020). Node host/port/name changes go through the reconfigure step. `async_setup_entry` removes registry entities/devices for deleted fixtures, and calls `controller.async_start_sending()` only after platforms are set up, so restored states are in the buffer before the first frame (avoids flicker).
- **Entities/devices**: each fixture is its own device, created in `async_setup_entry` with `async_get_or_create(via_device_id=<node device id>)` — not `DeviceInfo(via_device=...)`, which is deprecated (D-013, D-015). The entity's `DeviceInfo` only carries identifiers and `_attr_name = None`, so entity_id derives from the fixture name (`客厅灯带` → `light.ke_ting_deng_dai`).
- **Unload/remove**: universes that no longer carry any fixture get one all-zero frame (`controller.blackout`), all of them when the entry is disabled; `async_remove_entry` blacks out a deleted node with a throwaway controller (D-016). Plain HA shutdown sends nothing, so lights keep their state across restarts.
- **Discovery**: `async_setup` starts background ArtPoll every 5 min (only runs once any entry exists). Unique IDs: MAC via `format_mac` for discovered nodes, `host:port` for manual ones, plus `_async_abort_entries_match({host})` for cross-dedup.
- **Channel order** strings (R G B W C I T) must be a permutation of the type's default in `fixture.DEFAULT_ORDER`; validation lives in `normalize_order`.

## Translations

`strings.json` is the source; `translations/en.json` is a copy of it and `translations/zh-Hans.json` must be kept in sync by hand (same keys, including `selector` options and the `advanced` section under both `add_fixture` and `edit_fixture`).
