"""Enable custom integration loading in the Home Assistant test harness."""

import pytest


@pytest.fixture(autouse=True)
def enable_qnap_custom_integration(enable_custom_integrations):
    """Load this checkout's QNAP integration during tests."""
