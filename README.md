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

### Monitoring and power setup

Follow the [getting-started guide](docs/getting-started.md) to configure QNAP
monitoring and optional native Wake on LAN through the interface.
This experimental `feat/native-wol-assistant` branch adds consent-based WOL
setup and a QNAP **Power on** button on top of the separate shutdown/reboot
candidate `00ad474`. It uses the real native WOL config flow to reuse or create
entries, and delegates power-on to their `button.press` action. Physical device
and browser validation remain pending.

Energy support currently requires the exact library candidate described in
the development procedure. The manifest still names the existing published
`qnap-client==1.1.0`, whose released code lacks these methods. Distribution
requires a published client release containing energy support and a matching
manifest update. Use the isolated development procedure for this candidate.

The code's API-level minimum is Home Assistant **2025.3.0**, reflected in HACS.
The assisted flow and offline initialization are exercised in both HA 2025.3.0
and 2026.10.4 using simulated QTS and the real native WOL flow and entities.
Native WOL UI setup has been available since HA 2024.8. QNAP monitoring functions independently
of whether a WOL entry is configured.

Development deployment and rollback are documented in the
[isolated testing procedure](docs/development-testing.md). It identifies the
candidate library separately from the release needed for distribution.

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
| Username | — | QTS account with permissions for the features you want to use |
| Password | — | That account's password, entered locally in Home Assistant |
| Port | 8080 | QTS web interface port |
| Enable SSL | Off | Use HTTPS instead of HTTP |
| Verify SSL certificate | On | Validate the certificate chain and server identity. HTTPS is selected independently. |

To update your settings later, go to **Settings → Devices & Services**, find the QNAP integration, and click **Reconfigure**.

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

### Power buttons

**Power on** invokes the explicitly associated native WOL buttons. During
setup, confirm physical MACs, reuse existing entries and consent separately
before each missing entry is created. QTS MAC discovery establishes candidates
whose physical-port and WOL capability need confirmation. Network settings
remain owned by native WOL. **Options** provides manual selection and reversible
per-NAS suppression of suggestions.

Saved WOL associations permit QNAP initialization with the NAS offline.
Power on loads configured, enabled native targets and follows their registry
identity through renames. Disabled, removed or unresolved targets make it
unavailable until reviewed. QTS buttons and existing sensors retain their
monitoring availability. Deferred sensor/container registration resumes when
the first valid NAS data arrives. No packet is sent during setup.

The NAS device exposes **Shut down** and **Reboot** configuration buttons.
Each press authenticates an independent control client with the entry's
connection settings and invokes one public library method. Power requests
have no automatic retries. A concurrent press is rejected while another
power request is in progress.

A successful press records QTS CGI acceptance. Completion of shutdown or
reboot is observed separately. An uncertain result asks the user to check
the NAS before another action. Permission rejection affects the requested
action independently of monitoring. Both buttons follow the monitoring
coordinator's availability and become unavailable when a poll fails.
Monitoring resumes through normal read-only polling after connectivity and
authentication recover. Physical HA recovery still requires validation.

Optional remote power-on uses Home Assistant's native Wake on LAN button.
The [setup guide](docs/getting-started.md) explains the complete UI workflow.

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
- **Authentication** — The public client performs password login and reports pending second-factor challenges. The interactive adapter used in hardware trials is local test infrastructure. General MFA remains a separate contribution.
- **Detailed system health** — The `status` sensor returns only a summary (`Ready`/`Warning`/`Error`). Granular per-subsystem detail is not available via the CGI API.
- **Some QNAP models with unusual NIC naming** (e.g., QNAP-473e) — If a NIC key is missing from the API response, it is skipped gracefully without crashing setup.

## 📋 What's New in v3.0

### New Features
- **🐳 Container Station switches** — Start and stop Docker/LXC containers from Home Assistant
- **🔄 Firmware update entity** — Appears in HA's native update dashboard

### Architecture
- Config flow only — YAML configuration removed
- `runtime_data` typed config entry pattern
- `CoordinatorEntity` throughout — all entities share a single polling coordinator
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
