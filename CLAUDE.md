# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Home Assistant custom integration `artnet_light` (HACS, min HA 2024.11, Python ≥3.12 at runtime): discovers Art-Net nodes, and lets users add DMX fixtures (dimmer/CCT/RGB/RGBW/RGBWW) entirely through the config flow and options flow UI. User-facing docs are in Chinese; code/comments in English.

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
4. Run `python -m pytest tests/test_core.py -q` first; don't tag a red build.
5. One commit, Conventional Commits prefix (`feat:` / `fix:` / `refactor:` / `test:` / `docs:` / `chore:`), then an annotated tag: `git tag -a vX.Y.Z -m "vX.Y.Z: <summary>"`.

Doc-only changes (Plan/DECISIONS/README/CLAUDE.md) are committed with `docs:` but **not** version-bumped or tagged. Work on `main` directly (solo repo). Never push or create remotes/releases without asking — no remote is configured yet.

## Commands

Dev machine is Windows with only Python 3.11 (no Docker, no HA install). A scratch venv with pytest is used for local runs.

```bash
# HA-independent core tests (protocol, fixture math, UDP sender) — runs locally
python -m pytest tests/test_core.py -q
python -m pytest tests/test_core.py -q -k cct          # single test / subset

# Full suite incl. config/options flow tests — needs Linux + Python >=3.12
pip install -r requirements_test.txt && pytest

# Fake Art-Net node: answers ArtPoll, prints received DMX (run on a LAN machine other than the HA host; both need UDP 6454)
python tools/fake_node.py --name TestNode --universes 0 1
```

CI (`.github/workflows/validate.yml`): hassfest, HACS validation, full pytest on Ubuntu/Py3.13. `tests/ha/test_flows.py` has never been executed locally.

## Architecture

Two layers, strictly separated (DECISIONS D-009):

- **Pure core (stdlib only, no `homeassistant` imports)**: `const.py`, `artnet.py` (packet build/parse), `fixture.py` (fixture model + level math), `controller.py` (per-node UDP socket, 512-byte buffers per universe, send loop, fades). `tests/test_core.py` and `tools/fake_node.py` load these via a stub package `artnet_core` to bypass `__init__.py`; adding an HA import to any of them breaks local testing. Use relative imports only between core modules.
- **HA layer**: `__init__.py`, `config_flow.py`, `discovery.py`, `light.py`.

Data flow for a light command: `ArtNetLight.async_turn_on` → `Fixture.compute_levels()` (floats 0–1 per channel letter, min/max output applied, `T` exempt) → `ArtNetController.apply()` (optional fade interpolates floats) → `Fixture.encode()` (8/16-bit bytes) → `set_channels()` marks universe dirty → send loop emits ArtDmx.

Key cross-file facts:
- **Storage**: one config entry per node. `entry.data` = host/port/name/mac/universes; `entry.options` = send settings + `fixtures` (list of `Fixture.to_dict()`). Fixture `id` (uuid) is the entity unique_id and the device identifier.
- **Live updates**: any options save → update listener reloads the entry. `async_setup_entry` removes registry entities/devices for deleted fixtures, and calls `controller.async_start_sending()` only after platforms are set up, so restored states are in the buffer before the first frame (avoids flicker).
- **Entities**: each fixture is its own device (`via_device` = node device keyed by `entry_id`) with `_attr_name = None`, so entity_id derives from the fixture name (`客厅灯带` → `light.ke_ting_deng_dai`).
- **Discovery**: `async_setup` starts background ArtPoll every 5 min (only runs once any entry exists). Unique IDs: MAC via `format_mac` for discovered nodes, `host:port` for manual ones, plus `_async_abort_entries_match({host})` for cross-dedup.
- **Channel order** strings (R G B W C I T) must be a permutation of the type's default in `fixture.DEFAULT_ORDER`; validation lives in `normalize_order`.

## Translations

`strings.json` is the source; `translations/en.json` is a copy of it and `translations/zh-Hans.json` must be kept in sync by hand (same keys, including `selector` options and the `advanced` section under both `add_fixture` and `edit_fixture`).
