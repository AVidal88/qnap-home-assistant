"""Typed dataclasses for all qnap-client return types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SystemInfo:
    """Basic NAS system information."""

    model: str
    name: str
    serial_number: str
    firmware_version: str
    uptime_seconds: int
    system_temp: int | None = None


@dataclass
class SystemHealth:
    """Overall system health status."""

    status: str  # "Ready" | "Warning" | "Error"


@dataclass
class CpuStats:
    """CPU utilisation."""

    usage_percent: float
    cpu_temp: int | None = None


@dataclass
class MemoryStats:
    """RAM stats in megabytes."""

    total_mb: int
    free_mb: int
    used_mb: int


@dataclass
class NetworkInterface:
    """Stats for a single network interface."""

    name: str
    mac: str
    ip: str
    rx_bytes_per_sec: float
    tx_bytes_per_sec: float
    link_status: str = "Unknown"
    mask: str = ""
    max_speed: int = 0
    rx_packets: int = 0
    tx_packets: int = 0
    err_packets: int = 0


@dataclass
class DriveHealth:
    """SMART / health info for a single drive."""

    drive_number: int
    model: str
    health: str
    temperature: int | None


@dataclass
class VolumeStats:
    """Storage volume / pool statistics."""

    name: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    status: str


@dataclass
class FirmwareUpdate:
    """Firmware version info."""

    current_version: str
    latest_version: str | None


@dataclass
class FanStatus:
    """Fan sensor reading."""

    fan_number: int
    speed_rpm: int


@dataclass
class ExternalDrive:
    """Externally-connected USB / eSATA drive."""

    name: str
    total_bytes: int
    used_bytes: int


@dataclass
class Container:
    """Container Station container."""

    id: str
    name: str
    state: str
    image: str
    type: str = "docker"


@dataclass
class NasData:
    """Top-level aggregate of all NAS sensor data."""

    system_info: SystemInfo
    system_health: SystemHealth
    cpu: CpuStats
    memory: MemoryStats
    network_interfaces: list[NetworkInterface] = field(default_factory=list)
    drives: list[DriveHealth] = field(default_factory=list)
    volumes: list[VolumeStats] = field(default_factory=list)
    firmware: FirmwareUpdate | None = None
    fans: list[FanStatus] = field(default_factory=list)
    external_drives: list[ExternalDrive] = field(default_factory=list)
    containers: list[Container] = field(default_factory=list)
