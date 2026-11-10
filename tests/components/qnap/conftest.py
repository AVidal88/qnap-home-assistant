"""Fixtures for the custom integration; no real QTS requests are permitted."""

from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from qnap_client.models import (
    Container,
    CpuStats,
    DriveHealth,
    FirmwareUpdate,
    MemoryStats,
    NasData,
    NetworkInterface,
    SystemHealth,
    SystemInfo,
    VolumeStats,
)

from custom_components.qnap.const import DOMAIN

TEST_SERIAL = "QX1234567"


@pytest.fixture(autouse=True)
def custom_integration(enable_custom_integrations):
    """Load custom_components.qnap rather than the unrelated core integration."""


@pytest.fixture
def nas_data():
    """Synthetic application models; these do not prove a firmware API contract."""
    return NasData(
        system_info=SystemInfo("TS-453D", "Test NAS", TEST_SERIAL, "5.1.0.2548", 60),
        system_health=SystemHealth("Ready"),
        cpu=CpuStats(10, 55),
        memory=MemoryStats(8192, 4096, 4096),
        network_interfaces=[
            NetworkInterface(
                name="eth0",
                mac="00:11:22:33:44:55",
                ip="192.0.2.10",
                rx_bytes_per_sec=2000,
                tx_bytes_per_sec=1000,
            )
        ],
        drives=[DriveHealth(1, "Test drive", "good", 35)],
        volumes=[
            VolumeStats("DataVol1", 1000000000000, 500000000000, 500000000000, "Ready")
        ],
        firmware=FirmwareUpdate("5.1.0.2548", None),
        containers=[
            Container("abc123", "Example", "running", "example:latest", "docker")
        ],
    )


@pytest.fixture
def mock_config_entry():
    """A previously configured NAS with one physical MAC for WOL."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test NAS",
        unique_id=TEST_SERIAL,
        data={
            "host": "192.0.2.10",
            "username": "test",
            "password": "test-password",
            "port": 8080,
            "ssl": False,
            "verify_ssl": True,
        },
        options={
            "wol_macs": ["00:11:22:33:44:55"],
            "broadcast_address": "192.0.2.255",
            "broadcast_port": 9,
        },
    )


@pytest.fixture(autouse=True)
def mock_qnap_client(nas_data):
    """Intercept every production client at its import sites, including setup."""
    with (
        patch(
            "custom_components.qnap.coordinator.QnapClient", autospec=True
        ) as client_cls,
        patch(
            "custom_components.qnap.coordinator.ContainerStationClient", autospec=True
        ) as cs_cls,
        patch(
            "custom_components.qnap.config_flow.QnapClient", autospec=True
        ) as flow_cls,
    ):
        client = client_cls.return_value
        client.login = AsyncMock()
        client.get_all = AsyncMock(return_value=nas_data)
        client.close = AsyncMock()
        cs_cls.return_value.get_containers = AsyncMock(return_value=nas_data.containers)
        flow_client = flow_cls.return_value
        flow_client.__aenter__.return_value = flow_client
        flow_client.get_system_info.return_value = nas_data.system_info
        yield client


@pytest.fixture
def entity_registry_enabled_by_default():
    """Exercise optional diagnostic sensors as well as enabled entities."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield
