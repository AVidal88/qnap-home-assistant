"""Set up QNAP tests with the asynchronous public client models."""

from collections.abc import Generator
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from qnap_client.models import (
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
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_TIMEOUT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)

from custom_components.qnap.const import (
    DEFAULT_PORT,
    DEFAULT_SSL,
    DEFAULT_TIMEOUT,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

TEST_HOST = "192.0.2.10"
TEST_USERNAME = "test-user"
TEST_PASSWORD = "test-password"
TEST_NAS_NAME = "Test NAS"
TEST_SERIAL = "QX1234567"
INSTALLED_VERSION = "5.1.0.2548"


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Use stable Home Assistant serialization and the existing snapshots directory."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Enable optional sensors while exercising their entity states."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default", True
    ):
        yield


@pytest.fixture
def qnap_data() -> NasData:
    """Translate the existing synthetic fixture into public client models."""
    fixture_path = Path(__file__).parent / "fixtures" / "qnap_data.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    stats = fixture["system_stats"]
    system = stats["system"]
    memory = stats["memory"]
    uptime = stats["uptime"]
    return NasData(
        system_info=SystemInfo(
            model=system["model"],
            name=system["name"],
            serial_number=system["serial_number"],
            firmware_version=stats["firmware"]["version"],
            uptime_seconds=(
                uptime["days"] * 86400
                + uptime["hours"] * 3600
                + uptime["minutes"] * 60
                + uptime["seconds"]
            ),
            system_temp=system["temp_c"],
        ),
        system_health=SystemHealth(status=fixture["system_health"]),
        cpu=CpuStats(
            usage_percent=stats["cpu"]["usage_percent"],
            cpu_temp=stats["cpu"]["temp_c"],
        ),
        memory=MemoryStats(
            total_mb=memory["total"],
            free_mb=memory["free"],
            used_mb=memory["total"] - memory["free"],
        ),
        network_interfaces=[
            NetworkInterface(
                name=name,
                mac=interface["mac"],
                ip=interface["ip"],
                rx_bytes_per_sec=fixture["bandwidth"][name]["rx"],
                tx_bytes_per_sec=fixture["bandwidth"][name]["tx"],
                link_status=interface["link_status"],
                mask=interface["mask"],
                max_speed=interface["max_speed"],
                rx_packets=interface["rx_packets"],
                tx_packets=interface["tx_packets"],
                err_packets=interface["err_packets"],
            )
            for name, interface in stats["nics"].items()
        ],
        drives=[
            DriveHealth(
                drive_number=int(drive["drive_number"]),
                model=drive["model"],
                health=drive["health"],
                temperature=drive["temp_c"],
            )
            for drive in fixture["smart_drive_health"].values()
        ],
        volumes=[
            VolumeStats(
                name=name,
                total_bytes=volume["total_size"],
                free_bytes=volume["free_size"],
                used_bytes=volume["total_size"] - volume["free_size"],
                status="Ready",
            )
            for name, volume in fixture["volumes"].items()
        ],
        firmware=FirmwareUpdate(
            current_version=stats["firmware"]["version"],
            latest_version=fixture["firmware_update"],
        ),
    )


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock QNAP config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=TEST_NAS_NAME,
        unique_id=TEST_SERIAL,
        data={
            CONF_HOST: TEST_HOST,
            CONF_USERNAME: TEST_USERNAME,
            CONF_PASSWORD: TEST_PASSWORD,
            CONF_SSL: DEFAULT_SSL,
            CONF_VERIFY_SSL: DEFAULT_VERIFY_SSL,
            CONF_PORT: DEFAULT_PORT,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
        },
    )


@pytest.fixture
def mock_container_station() -> Generator[MagicMock]:
    """Keep optional Container Station requests offline."""
    with patch(
        "custom_components.qnap.coordinator.ContainerStationClient", autospec=True
    ) as mock_class:
        client = mock_class.return_value
        client.get_containers.return_value = []
        yield client


@pytest.fixture
def mock_qnap_client(
    qnap_data: NasData, mock_container_station: MagicMock
) -> Generator[MagicMock]:
    """Mock the coordinator's asynchronous public QnapClient."""
    with patch(
        "custom_components.qnap.coordinator.QnapClient", autospec=True
    ) as mock_class:
        client = mock_class.return_value
        client.get_all.return_value = qnap_data
        client.get_system_info.return_value = qnap_data.system_info
        yield client


@pytest.fixture
def mock_setup_entry() -> Generator[MagicMock]:
    """Override async_setup_entry during config flow tests."""
    with patch(
        "custom_components.qnap.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def qnap_connect(qnap_data: NasData) -> Generator[MagicMock]:
    """Mock the public client used by config flow validation."""
    with patch(
        "custom_components.qnap.config_flow.QnapClient", autospec=True
    ) as mock_class:
        client = mock_class.return_value
        client.__aenter__.return_value = client
        client.get_system_info.return_value = qnap_data.system_info
        yield client
