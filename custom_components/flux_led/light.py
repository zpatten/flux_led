"""Support for Flux lights."""
import logging
import random
import time

from .flux_led_x import BulbScanner, WifiLedBulb
import voluptuous as vol

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    EFFECT_COLORLOOP,
    EFFECT_RANDOM,
    PLATFORM_SCHEMA,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR,
    SUPPORT_COLOR_TEMP,
    SUPPORT_EFFECT,
    LightEntity,
)
from homeassistant.const import ATTR_MODE, CONF_DEVICES, CONF_NAME, CONF_PROTOCOL
import homeassistant.helpers.config_validation as cv
import homeassistant.util.color as color_util

_LOGGER = logging.getLogger(__name__)

CONF_AUTOMATIC_ADD = "automatic_add"
CONF_CUSTOM_EFFECT = "custom_effect"
CONF_COLORS = "colors"
CONF_SPEED_PCT = "speed_pct"
CONF_TRANSITION = "transition"

DOMAIN = "flux_led"

SUPPORT_FLUX_LED = SUPPORT_BRIGHTNESS | SUPPORT_EFFECT | SUPPORT_COLOR

MODE_RGB = "rgb"
MODE_RGBW = "rgbw"

# This mode enables white value to be controlled by brightness.
# RGB value is ignored when this mode is specified.
MODE_WHITE = "w"

# Constant color temp values for 2 flux_led special modes
# Warm-white and Cool-white modes
COLOR_TEMP_WARM_VS_COLD_WHITE_CUT_OFF = 285

# List of supported effects which aren't already declared in LIGHT
EFFECT_RED_FADE = "red_fade"
EFFECT_GREEN_FADE = "green_fade"
EFFECT_BLUE_FADE = "blue_fade"
EFFECT_YELLOW_FADE = "yellow_fade"
EFFECT_CYAN_FADE = "cyan_fade"
EFFECT_PURPLE_FADE = "purple_fade"
EFFECT_WHITE_FADE = "white_fade"
EFFECT_RED_GREEN_CROSS_FADE = "rg_cross_fade"
EFFECT_RED_BLUE_CROSS_FADE = "rb_cross_fade"
EFFECT_GREEN_BLUE_CROSS_FADE = "gb_cross_fade"
EFFECT_COLORSTROBE = "colorstrobe"
EFFECT_RED_STROBE = "red_strobe"
EFFECT_GREEN_STROBE = "green_strobe"
EFFECT_BLUE_STROBE = "blue_strobe"
EFFECT_YELLOW_STROBE = "yellow_strobe"
EFFECT_CYAN_STROBE = "cyan_strobe"
EFFECT_PURPLE_STROBE = "purple_strobe"
EFFECT_WHITE_STROBE = "white_strobe"
EFFECT_COLORJUMP = "colorjump"
EFFECT_CUSTOM = "custom"

EFFECT_MAP = {
    EFFECT_COLORLOOP: 0x25,
    EFFECT_RED_FADE: 0x26,
    EFFECT_GREEN_FADE: 0x27,
    EFFECT_BLUE_FADE: 0x28,
    EFFECT_YELLOW_FADE: 0x29,
    EFFECT_CYAN_FADE: 0x2A,
    EFFECT_PURPLE_FADE: 0x2B,
    EFFECT_WHITE_FADE: 0x2C,
    EFFECT_RED_GREEN_CROSS_FADE: 0x2D,
    EFFECT_RED_BLUE_CROSS_FADE: 0x2E,
    EFFECT_GREEN_BLUE_CROSS_FADE: 0x2F,
    EFFECT_COLORSTROBE: 0x30,
    EFFECT_RED_STROBE: 0x31,
    EFFECT_GREEN_STROBE: 0x32,
    EFFECT_BLUE_STROBE: 0x33,
    EFFECT_YELLOW_STROBE: 0x34,
    EFFECT_CYAN_STROBE: 0x35,
    EFFECT_PURPLE_STROBE: 0x36,
    EFFECT_WHITE_STROBE: 0x37,
    EFFECT_COLORJUMP: 0x38,
}
EFFECT_CUSTOM_CODE = 0x60

TRANSITION_GRADUAL = "gradual"
TRANSITION_JUMP = "jump"
TRANSITION_STROBE = "strobe"

FLUX_EFFECT_LIST = sorted(list(EFFECT_MAP)) + [EFFECT_RANDOM]

CUSTOM_EFFECT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_COLORS): vol.All(
            cv.ensure_list,
            vol.Length(min=1, max=16),
            [
                vol.All(
                    vol.ExactSequence((cv.byte, cv.byte, cv.byte)), vol.Coerce(tuple)
                )
            ],
        ),
        vol.Optional(CONF_SPEED_PCT, default=50): vol.All(
            vol.Range(min=0, max=100), vol.Coerce(int)
        ),
        vol.Optional(CONF_TRANSITION, default=TRANSITION_GRADUAL): vol.All(
            cv.string, vol.In([TRANSITION_GRADUAL, TRANSITION_JUMP, TRANSITION_STROBE])
        ),
    }
)

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(ATTR_MODE, default=MODE_RGBW): vol.All(
            cv.string, vol.In([MODE_RGBW, MODE_RGB, MODE_WHITE])
        ),
        vol.Optional(CONF_PROTOCOL): vol.All(cv.string, vol.In(["ledenet"])),
        vol.Optional(CONF_CUSTOM_EFFECT): CUSTOM_EFFECT_SCHEMA,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_DEVICES, default={}): {cv.string: DEVICE_SCHEMA},
        vol.Optional(CONF_AUTOMATIC_ADD, default=False): cv.boolean,
    }
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Flux lights."""
    lights = []
    light_ips = []

    for ipaddr, device_config in config.get(CONF_DEVICES, {}).items():
        device = {}
        device["name"] = device_config[CONF_NAME]
        device["ipaddr"] = ipaddr
        device[CONF_PROTOCOL] = device_config.get(CONF_PROTOCOL)
        device[ATTR_MODE] = device_config[ATTR_MODE]
        device[CONF_CUSTOM_EFFECT] = device_config.get(CONF_CUSTOM_EFFECT)
        light = FluxLight(device)
        lights.append(light)
        light_ips.append(ipaddr)

    if not config.get(CONF_AUTOMATIC_ADD, False):
        add_entities(lights, True)
        return

    # Find the bulbs on the LAN
    scanner = BulbScanner()
    scanner.scan(timeout=10)
    for device in scanner.getBulbInfo():
        ipaddr = device["ipaddr"]
        if ipaddr in light_ips:
            continue
        device["name"] = f"{device['id']} {ipaddr}"
        device[ATTR_MODE] = None
        device[CONF_PROTOCOL] = None
        device[CONF_CUSTOM_EFFECT] = None
        light = FluxLight(device)
        lights.append(light)

    add_entities(lights, True)


class FluxLight(LightEntity):
    """Representation of a Flux light."""

    def __init__(self, device):
        """Initialize the light."""
        self._name = device["name"]
        self._ipaddr = device["ipaddr"]
        self._protocol = device[CONF_PROTOCOL]
        self._mode = device[ATTR_MODE]
        self._custom_effect = device[CONF_CUSTOM_EFFECT]
        self._color_temp = None
        self._bulb = None
        self._error_reported = False

    def _connect(self):
        """Connect to Flux light."""

        self._bulb = WifiLedBulb(self._ipaddr, timeout=5)
        if self._protocol:
            self._bulb.setProtocol(self._protocol)

        # After bulb object is created the status is updated. We can
        # now set the correct mode if it was not explicitly defined.
        if not self._mode:
            if self._bulb.rgbwcapable:
                self._mode = MODE_RGBW
            else:
                self._mode = MODE_RGB

        _LOGGER.warning("FLUX_LED[%s] - protocol:%s, mode:%s, rgbwcapable:%s", self._name, self._bulb.protocol, self._bulb.mode, self._bulb.rgbwcapable)
        _LOGGER.warning("FLUX_LED[%s] - %s", self._name, str(self._bulb))
        

    def _disconnect(self):
        """Disconnect from Flux light."""
        self._bulb = None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._bulb is not None

    @property
    def name(self):
        """Return the name of the device if any."""
        return self._name

    @property
    def is_on(self):
        """Return true if device is on."""
        return self._bulb.isOn()

    @property
    def brightness(self):
        """Return the brightness of this light between 0..255."""
        if self._mode == MODE_WHITE:
            return self._bulb.getRgbw()[3]
            # return self.white_value

        return self._bulb.brightness

    @property
    def hs_color(self):
        """Return the color property."""
        return color_util.color_RGB_to_hs(*self._bulb.getRgb())

    @property
    def color_temp(self):
        """Return the CT color value in mireds."""
        return self._color_temp

    @property
    def min_mireds(self):
        """Return the coldest color_temp that this light supports."""
        return 112

    @property
    def max_mireds(self):
        """Return the warmest color_temp that this light supports."""
        return 400
        
    @property
    def supported_features(self):
        """Flag supported features."""
        if self._mode == MODE_RGBW:
            return SUPPORT_FLUX_LED | SUPPORT_COLOR_TEMP

        if self._mode == MODE_WHITE:
            return SUPPORT_BRIGHTNESS

        return SUPPORT_FLUX_LED

    @property
    def effect_list(self):
        """Return the list of supported effects."""
        if self._custom_effect:
            return FLUX_EFFECT_LIST + [EFFECT_CUSTOM]

        return FLUX_EFFECT_LIST

    @property
    def effect(self):
        """Return the current effect."""
        current_mode = self._bulb.raw_state[3]

        if current_mode == EFFECT_CUSTOM_CODE:
            return EFFECT_CUSTOM

        for effect, code in EFFECT_MAP.items():
            if current_mode == code:
                return effect

        return None

    def turn_on(self, **kwargs):
        _LOGGER.warning("FLUX_LED[%s] - %s", self._name, str(self._bulb))

        """Turn the specified or all lights on."""
        if not self.is_on:
            self._bulb.turnOn()

        brightness = kwargs.get(ATTR_BRIGHTNESS)
        # Preserve current brightness on color/white level change
        if brightness is None:
            brightness = self.brightness

        hs_color = kwargs.get(ATTR_HS_COLOR)
        if hs_color:
            rgb = color_util.color_hs_to_RGB(*hs_color)
        else:
            rgb = None

        effect = kwargs.get(ATTR_EFFECT)
        if rgb is not None or effect is not None:
            self._color_temp = None

        color_temp = kwargs.get(ATTR_COLOR_TEMP)
        if rgb is None and color_temp is None:
          color_temp = self.color_temp

        # handle special modes
        if color_temp is not None:
            self._color_temp = color_temp
            kelvin = color_util.color_temperature_mired_to_kelvin(color_temp)
            rgb = color_util.color_temperature_to_rgb(kelvin)
            if self._mode == MODE_RGBW:
                _LOGGER.warning("FLUX_LED[%s] - color_temp:%s, rgb:%s, brightness:%s", self._name, color_temp, rgb, brightness)
                self._bulb.setRgbw(*tuple(rgb), w=brightness, brightness=brightness)
                return

        # Show warning if effect set with rgb, brightness, or white level
        if effect and (brightness or white or rgb):
            _LOGGER.warning(
                "RGB, brightness and white level are ignored when"
                " an effect is specified for a flux bulb"
            )

        # Random color effect
        if effect == EFFECT_RANDOM:
            self._bulb.setRgb(
                random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
            )
            return

        if effect == EFFECT_CUSTOM:
            if self._custom_effect:
                self._bulb.setCustomPattern(
                    self._custom_effect[CONF_COLORS],
                    self._custom_effect[CONF_SPEED_PCT],
                    self._custom_effect[CONF_TRANSITION],
                )
            return

        # Effect selection
        if effect in EFFECT_MAP:
            self._bulb.setPresetPattern(EFFECT_MAP[effect], 50)
            return

        # Preserve color on brightness/white level change
        if rgb is None:
            rgb = self._bulb.getRgb()

        _LOGGER.warning("FLUX_LED[%s] - rgb:%s, brightness:%s", self._name, rgb, brightness)

        # handle W only mode (use brightness instead of white value)
        if self._mode == MODE_WHITE:
            self._bulb.setRgbw(0, 0, 0, w=brightness)

        # handle RGBW mode
        elif self._mode == MODE_RGBW:
            self._bulb.setRgbw(*tuple(rgb), w=0, brightness=brightness)

        # handle RGB mode
        else:
            self._bulb.setRgb(*tuple(rgb), brightness=brightness)

    def turn_off(self, **kwargs):
        """Turn the specified or all lights off."""
        self._bulb.turnOff()

    def update(self):
        """Synchronize state with bulb."""
        if not self.available:
            try:
                self._connect()
                self._error_reported = False
            except OSError:
                self._disconnect()
                if not self._error_reported:
                    _LOGGER.warning(
                        "Failed to connect to bulb %s, %s", self._ipaddr, self._name
                    )
                    self._error_reported = True
                return

        self._bulb.update_state(retry=2)
