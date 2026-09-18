"""Constants for the Gouly integration."""

DOMAIN = "gouly"
MANUFACTURER = "Gouly"

CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_PROTOCOL_VERSION = "protocol_version"
CONF_DEVICES_JSON = "devices_json"
CONF_DEVICE = "device"
CONF_PRESETS_FILE = "presets_file"
CONF_FAVOURITES = "favourites"
CONF_PRESET_EFFECTS = "preset_effects"

# How many presets the light's effect list offers.
PRESET_EFFECTS_FAVOURITES = "favourites"
PRESET_EFFECTS_ALL = "all"
PRESET_EFFECTS_NONE = "none"
DEFAULT_PRESET_EFFECTS = PRESET_EFFECTS_FAVOURITES

DEFAULT_PROTOCOL_VERSION = 3.5
DEFAULT_EFFECT_SPEED = 128
