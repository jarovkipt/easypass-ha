"""Pytest configuration for Thai Easy Pass."""

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load this repository's custom component."""
    yield


def pytest_configure(config) -> None:
    """Register local markers used by the Home Assistant test plugin."""
    config.addinivalue_line("markers", "enable_socket: allow real socket access")
