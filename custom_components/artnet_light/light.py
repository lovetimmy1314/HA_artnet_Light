"""Light entities for Art-Net fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from . import ArtNetConfigEntry
from .const import (
    CONF_DEFAULT_TRANSITION,
    CONF_FIXTURES,
    DEFAULT_OPTIONS,
    DOMAIN,
    TYPE_CCT,
    TYPE_DIMMER,
    TYPE_RGB,
    TYPE_RGBW,
    TYPE_RGBWW,
)
from .controller import ArtNetController
from .fixture import Fixture

COLOR_MODES = {
    TYPE_DIMMER: ColorMode.BRIGHTNESS,
    TYPE_CCT: ColorMode.COLOR_TEMP,
    TYPE_RGB: ColorMode.RGB,
    TYPE_RGBW: ColorMode.RGBW,
    TYPE_RGBWW: ColorMode.RGBWW,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArtNetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    options = {**DEFAULT_OPTIONS, **entry.options}
    async_add_entities(
        ArtNetLight(
            entry.runtime_data,
            Fixture.from_dict(data),
            float(options[CONF_DEFAULT_TRANSITION]),
        )
        for data in options[CONF_FIXTURES]
    )


@dataclass
class ArtNetLightExtraData(ExtraStoredData):
    """Last brightness/colour, stored even while off (the off state carries no attributes)."""

    brightness: int | None
    rgb_color: tuple[int, int, int] | None
    rgbw_color: tuple[int, int, int, int] | None
    rgbww_color: tuple[int, int, int, int, int] | None
    color_temp_kelvin: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "brightness": self.brightness,
            "rgb_color": self.rgb_color,
            "rgbw_color": self.rgbw_color,
            "rgbww_color": self.rgbww_color,
            "color_temp_kelvin": self.color_temp_kelvin,
        }


class ArtNetLight(LightEntity, RestoreEntity):
    """One DMX fixture."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_supported_features = LightEntityFeature.TRANSITION

    def __init__(
        self,
        controller: ArtNetController,
        fixture: Fixture,
        default_transition: float,
    ) -> None:
        self._controller = controller
        self._fixture = fixture
        self._default_transition = default_transition

        self._attr_unique_id = fixture.id
        self._attr_color_mode = COLOR_MODES[fixture.type]
        self._attr_supported_color_modes = {self._attr_color_mode}
        # The device itself is created and linked to the node in __init__.async_setup_entry
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, fixture.id)})
        self._attr_extra_state_attributes = {
            "universe": fixture.universe,
            "dmx_start_channel": fixture.start_channel,
            "dmx_end_channel": fixture.end_channel,
            "channel_order": fixture.channel_order,
        }

        self._attr_is_on = False
        self._attr_brightness = 255
        self._attr_rgb_color = (255, 255, 255)
        self._attr_rgbw_color = (0, 0, 0, 255)
        self._attr_rgbww_color = (0, 0, 0, 255, 255)
        if fixture.type == TYPE_CCT:
            self._attr_min_color_temp_kelvin = fixture.min_kelvin
            self._attr_max_color_temp_kelvin = fixture.max_kelvin
            self._attr_color_temp_kelvin = (fixture.min_kelvin + fixture.max_kelvin) // 2

    async def async_added_to_hass(self) -> None:
        """Restore the last known state and push it to the node immediately."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
            # Extra data has the values even when the light was off; states saved
            # by <= 0.1.2 only have them in the attributes, and only while on.
            extra = await self.async_get_last_extra_data()
            self._restore_values(extra.as_dict() if extra is not None else last.attributes)
        self._output(0)

    def _restore_values(self, values: Any) -> None:
        if brightness := values.get(ATTR_BRIGHTNESS):
            self._attr_brightness = int(brightness)
        if (rgb := values.get(ATTR_RGB_COLOR)) and len(rgb) == 3 and self._fixture.type == TYPE_RGB:
            self._attr_rgb_color = tuple(rgb)
        if (rgbw := values.get(ATTR_RGBW_COLOR)) and len(rgbw) == 4:
            self._attr_rgbw_color = tuple(rgbw)
        if (rgbww := values.get(ATTR_RGBWW_COLOR)) and len(rgbww) == 5:
            self._attr_rgbww_color = tuple(rgbww)
        if (kelvin := values.get(ATTR_COLOR_TEMP_KELVIN)) and self._fixture.type == TYPE_CCT:
            self._attr_color_temp_kelvin = int(kelvin)

    @property
    def extra_restore_state_data(self) -> ArtNetLightExtraData:
        return ArtNetLightExtraData(
            self._attr_brightness,
            self._attr_rgb_color,
            self._attr_rgbw_color,
            self._attr_rgbww_color,
            self._attr_color_temp_kelvin if self._fixture.type == TYPE_CCT else None,
        )

    def _output(self, transition: float) -> None:
        levels = self._fixture.compute_levels(
            is_on=bool(self._attr_is_on),
            brightness=self._attr_brightness or 255,
            rgb=self._attr_rgb_color,
            rgbw=self._attr_rgbw_color,
            rgbww=self._attr_rgbww_color,
            kelvin=self._attr_color_temp_kelvin,
        )
        self._controller.apply(self._fixture, levels, transition)

    def _transition(self, kwargs: dict[str, Any]) -> float:
        return float(kwargs.get(ATTR_TRANSITION, self._default_transition))

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
        if ATTR_RGB_COLOR in kwargs:
            self._attr_rgb_color = kwargs[ATTR_RGB_COLOR]
        if ATTR_RGBW_COLOR in kwargs:
            self._attr_rgbw_color = kwargs[ATTR_RGBW_COLOR]
        if ATTR_RGBWW_COLOR in kwargs:
            self._attr_rgbww_color = kwargs[ATTR_RGBWW_COLOR]
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            self._attr_color_temp_kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
        if not self._attr_brightness:
            self._attr_brightness = 255
        self._attr_is_on = True
        self._output(self._transition(kwargs))
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Brightness is kept so the next turn_on returns to the previous level
        self._attr_is_on = False
        self._output(self._transition(kwargs))
        self.async_write_ha_state()
