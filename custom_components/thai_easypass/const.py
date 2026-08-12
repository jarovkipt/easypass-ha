"""Constants for the Thai Easy Pass integration."""

import logging
from datetime import timedelta

DOMAIN = "thai_easypass"
PLATFORMS = ["sensor"]

CONF_USERNAME = "username"
CONF_PASSWORD = "password"

DEFAULT_UPDATE_INTERVAL = timedelta(minutes=30)

MANUFACTURER = "EXAT"
MODEL = "Easy Pass"

LOGGER = logging.getLogger(__package__)

