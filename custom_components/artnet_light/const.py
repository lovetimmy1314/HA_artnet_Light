"""Constants for the Art-Net Light integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "artnet_light"

DEFAULT_PORT: Final = 6454
DEFAULT_NAME: Final = "Art-Net Node"

# Entry data
CONF_MAC: Final = "mac"
CONF_UNIVERSES: Final = "universes"

# Entry options
CONF_FIXTURES: Final = "fixtures"
CONF_SEND_MODE: Final = "send_mode"
CONF_KEEPALIVE: Final = "keepalive"
CONF_FPS: Final = "fps"
CONF_DEFAULT_TRANSITION: Final = "default_transition"

SEND_MODE_ON_CHANGE: Final = "on_change"
SEND_MODE_CONTINUOUS: Final = "continuous"
SEND_MODES: Final = [SEND_MODE_ON_CHANGE, SEND_MODE_CONTINUOUS]

DEFAULT_OPTIONS: Final = {
    CONF_SEND_MODE: SEND_MODE_ON_CHANGE,
    CONF_KEEPALIVE: 1.0,
    CONF_FPS: 30,
    CONF_DEFAULT_TRANSITION: 0.0,
    CONF_FIXTURES: [],
}

# Fixture fields
CONF_FIXTURE_ID: Final = "id"
CONF_FIXTURE_TYPE: Final = "type"
CONF_UNIVERSE: Final = "universe"
CONF_START_CHANNEL: Final = "start_channel"
CONF_BITS: Final = "bits"
CONF_CHANNEL_ORDER: Final = "channel_order"
CONF_CCT_MODE: Final = "cct_mode"
CONF_MIN_KELVIN: Final = "min_kelvin"
CONF_MAX_KELVIN: Final = "max_kelvin"
CONF_MIN_OUTPUT: Final = "min_output"
CONF_MAX_OUTPUT: Final = "max_output"
CONF_ADVANCED: Final = "advanced"
CONF_DELETE: Final = "delete"

TYPE_DIMMER: Final = "dimmer"
TYPE_CCT: Final = "cct"
TYPE_RGB: Final = "rgb"
TYPE_RGBW: Final = "rgbw"
TYPE_RGBWW: Final = "rgbww"
FIXTURE_TYPES: Final = [TYPE_DIMMER, TYPE_CCT, TYPE_RGB, TYPE_RGBW, TYPE_RGBWW]

# CCT: cold/warm white PWM channels, or intensity + colour temperature channels
CCT_MODE_CW: Final = "cold_warm"
CCT_MODE_IT: Final = "intensity_temp"
CCT_MODES: Final = [CCT_MODE_CW, CCT_MODE_IT]

DEFAULT_MIN_KELVIN: Final = 2700
DEFAULT_MAX_KELVIN: Final = 6500

DISCOVERY_TIMEOUT: Final = 3.0
DISCOVERY_INTERVAL_MIN: Final = 5
