# QNAP NAS Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/disforw/qnap.svg)](https://github.com/disforw/qnap/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 👋 Welcome Back — v3.0

After spending considerable time trying to get improvements accepted into Home Assistant core, active development is returning to this standalone HACS integration. The upstream PR process is slow by design — reviewers are volunteers with limited bandwidth, and even clean, well-tested code can sit for months before getting attention. Architectural discussions that should take a day can stretch into weeks. That's not a criticism of the HA team; it's just the reality of maintaining a massive open-source project at scale.

What it means for you is that **this integration moves faster**. Bug fixes ship when they're ready. New features — Container Station support, firmware update entities, and whatever comes next — don't have to survive a gauntlet of architectural review before reaching your Home Assistant instance.

v3.0 is a full rewrite. Config flow only, modern architecture throughout, and several features that were on the wishlist for years. If you've been using the built-in core integration, you can migrate to this one — it uses the same configuration structure.

## ✨ What It Does

Monitor your QNAP NAS directly from Home Assistant. Track CPU, memory, network, drive, and volume statistics as native sensor entities. Get notified when new firmware is available through HA's update dashboard. If you run Container Station on your QNAP, start and stop Docker containers with switch entities — no SSH required.

## 📦 Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three-dot menu (⋮) in the top right → **Custom repositories**
3. Add `https://github.com/disforw/qnap` with category **Integration**
4. Search for **QNAP** and install it
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration** and search for **QNAP**

### Manual

1. Download the latest release from [GitHub Releases](https://github.com/disforw/qnap/releases)
2. Copy the `custom_components/qnap` folder into your HA `config/custom_components/` directory
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration** and search for **QNAP**

## ⚙️ Configuration

The integration uses a UI config flow — no YAML needed.

| Field | Default | Description |
|---|---|---|
| Host | — | Hostname or IP address of your QNAP NAS |
| Username | — | QTS admin account username |
| Password | — | QTS admin account password |
| Port | 8080 | QTS web interface port |
| Enable SSL | Off | Use HTTPS instead of HTTP |
| Verify SSL certificate | On | Validate the SSL cert (disable for self-signed certs) |

To update your settings later, go to **Settings → Devices & Services**, find the QNAP integration, and click **Reconfigure**.

## Wake-on-LAN (working branch)

This branch adds a **Wake on LAN** button. Configure it in **Settings → Devices &
Services → QNAP → Configure**. Add the physical MAC address of every WOL-capable
NIC, an IPv4 broadcast address (default `255.255.255.255`), and UDP port (default
`9`; QNAP also documents `40000`). Duplicate MACs are removed. Clear the MAC list
to remove the wake button. Options can be changed while QTS is unreachable.

The button is available even if the NAS is off, authentication fails, or Home
Assistant restarts while QTS is unreachable. A press sends one magic packet per
configured MAC; it does not authenticate, poll QTS, or confirm that the NAS booted.
After the first real response, monitoring entities are added; later connection
failures mark them unavailable. Recovery uses the existing five-minute poll.
Initial installation still requires a reachable NAS to establish its identity.

Enable WOL in QTS/QuTS hero and verify support for the exact model and NIC.
EuP disables WOL. After removing NAS power while it is off, QNAP documents that a
manual power-on is needed before WOL works again. Broadcast routing/firewall,
VLAN, and container-network settings must permit delivery from Home Assistant.
HA running on the NAS itself cannot wake that NAS after it shuts down.

For LACP, configure physical port MACs explicitly. A bond/virtual interface MAC
does not establish which physical adapters can wake. Test each relevant port and
the actual switch topology. One broadcast destination is supported per NAS;
multiple subnets may require network configuration or a later per-NIC destination
feature. No universal LACP or 10GbE support is claimed.

**Shutdown and restart are not implemented.** Public examples did not establish
an authenticated request/acceptance contract for QTS 5.2 or QuTS hero. No real NAS
power action has been executed during development. See the [research and physical
acceptance plan](docs/power-control-research.md) for evidence and remaining work.

This branch requires **Home Assistant 2026.10.4 or later**, the version used for
integration tests, and a **local, unreleased `qnap-client==1.1.1`** candidate.
It is not ready for an ordinary HACS install until that client version is
published. The old `2024.1` HACS minimum was not valid for the APIs used here;
older HA versions have not been tested by this contribution.

## Development validation

On Linux with Python 3.14 and sibling `qnap` / `python-qnap` checkouts:

```sh
python3.14 -m venv .venv
. .venv/bin/activate
pip install -r requirements_test.txt -e ../python-qnap
python -m pytest -q
python -m pip check
ruff check custom_components tests
ruff format --check custom_components tests
```

Tests use Home Assistant 2026.10.4 and block network sockets; WOL transmission
and QTS access are mocked. Synthetic client models verify integration behavior,
not firmware response formats or physical NAS compatibility. The client repository
also has separate HTTP transport tests using an in-process loopback server.
Hassfest/HACS workflows and physical acceptance are separate validation steps.
The new pytest workflow requires the client release before it can pass remotely.

## 📊 Available Entities

### Sensors

Most per-device sensors (drives, volumes, network interfaces) are **disabled by default**. Enable them in **Settings → Entities**.

| Entity | Description | Unit | Device Class | State Class |
|---|---|---|---|---|
| Status | Overall system health (`normal` / `warning` / `error`) | — | — | — |
| System temperature | Chassis temperature | °C | Temperature | Measurement |
| CPU temperature | CPU temperature | °C | Temperature | Measurement |
| CPU usage | CPU utilization percentage | % | — | Measurement |
| Memory available | Free RAM | GiB | Data size | Measurement |
| Memory used | Used RAM | GiB | Data size | Measurement |
| Memory usage | RAM utilization percentage | % | — | Measurement |
| `<NIC>` link | Network interface link status | — | — | — |
| `<NIC>` upload | Network upload throughput | MiB/s | Data rate | Measurement |
| `<NIC>` download | Network download throughput | MiB/s | Data rate | Measurement |
| Drive `<N>` status | SMART health status for each drive | — | — | — |
| Drive `<N>` temperature | Drive temperature | °C | Temperature | Measurement |
| Used space (`<volume>`) | Used storage on each volume | GiB | Data size | Measurement |
| Free space (`<volume>`) | Free storage on each volume | GiB | Data size | Measurement |
| Volume used (`<volume>`) | Volume utilization percentage | % | — | Measurement |

Per-NIC sensors are created for each network interface reported by the NAS. Per-drive and per-volume sensors are similarly created for each drive and volume.

### Firmware Update

The integration registers a **firmware update entity** that appears in HA's native update dashboard (**Settings → Updates**). When QNAP releases new firmware, the entity changes state and you can be notified via standard HA update notifications. The entity is **read-only** — it tells you an update is available, but firmware installation must be done through the QNAP web UI.

### 🐳 Container Station Switches

[Container Station](https://www.qnap.com/en/software/container-station) is QNAP's built-in Docker and LXC runtime. When Container Station is installed and running, the integration creates a **switch entity for each container** — flipping the switch starts or stops the container.

| Entity | State On | State Off | Extra Attributes |
|---|---|---|---|
| `<container name>` | Running | Stopped | `image`, `container_type`, `container_id` |

Container switches use the Container Station v3 API (QTS Bearer token auth for reads, CS session auth for start/stop). If Container Station is not installed or accessible, the integration continues to work normally — container switches simply won't appear.

## ⚠️ Known Limitations

- **Fan speed sensors** — Fan data parsing implemented in `qnap-client`; accuracy against real hardware not yet verified.
- **External drive sensors** — Supported in `qnap-client`; accuracy against real hardware not yet verified.
- **MFA authentication** — Not supported. The QNAP CGI API does not expose a TOTP endpoint. Use a dedicated service account without MFA.
- **Detailed system health** — The `status` sensor returns only a summary (`Ready`/`Warning`/`Error`). Granular per-subsystem detail is not available via the CGI API.
- **Some QNAP models with unusual NIC naming** (e.g., QNAP-473e) — If a NIC key is missing from the API response, it is skipped gracefully without crashing setup.

## 📋 What's New in v3.0

### New Features
- **🐳 Container Station switches** — Start and stop Docker/LXC containers from Home Assistant
- **🔄 Firmware update entity** — Appears in HA's native update dashboard

### Architecture
- Config flow only — YAML configuration removed
- `runtime_data` typed config entry pattern
- Telemetry entities use `CoordinatorEntity` and share a polling coordinator; the WOL button is independent of QTS availability
- `_attr_has_entity_name = True` + `translation_key` on all sensors
- Non-fatal coordinator sections — Container Station and firmware update failures don't crash the integration

### Bug Fixes
- Fixed coordinator crash when firmware update API returns unexpected response
- Fixed drive temperature sensor reporting `0` instead of `None` when temperature data is unavailable
- Fixed `KeyError` crash in config flow on QNAP models with non-standard NIC speed keys
- Fixed `hacs.json` missing `switch` and `update` domains and incorrect `iot_class`
- Fixed firmware update entity using wrong `EntityCategory` (`CONFIG` → `DIAGNOSTIC`)

## 🤝 Contributing

Issues and PRs welcome. If you're reporting a bug, include:
- Your QNAP model and QTS version
- The relevant Home Assistant logs (`custom_components.qnap`)
- Whether Container Station is installed

For new features, open an issue first to discuss before writing code.

## 📄 License

MIT — see [LICENSE](LICENSE)
