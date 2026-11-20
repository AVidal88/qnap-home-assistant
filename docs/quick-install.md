# Install the development bundle

This development ZIP contains the assisted WOL integration and the exact
`qnap-client` candidate `b2f467a7dc5899d748d901c1d7549436758429d6`.
Its `SOURCE.json` records the integration revision and source fingerprints.
It requires Home Assistant 2025.3.0 or newer.

## Install in the Home Assistant instance chosen for the trial

1. Take the instance's normal HA backup. If QNAP is already installed, copy
   `/config/custom_components/qnap` to a backup location outside
   `/config/custom_components`, keeping that copy private.
2. Extract the development ZIP on your computer. Use your usual access to HA's
   configuration files to replace `/config/custom_components/qnap` with the
   supplied `custom_components/qnap` folder. Replace the entire component
   folder so older files are kept only in the backup.
3. Restart **Home Assistant** from **Settings → System → Restart Home
   Assistant**. Restarting the NAS belongs to a separately authorized trial.
4. For a new QNAP entry, open **Settings → Devices & services → Add integration
   → QNAP**. For an existing entry, use **Configure / Options** to access the
   assisted WOL setup. Enter QTS credentials directly in HA.
5. Verify the NAS identity, credible sensor values, Shutdown/Reboot controls
   and reload recovery. Power on becomes available when the selected native
   WOL targets are configured, enabled and loaded.

HA resolves the bundle's `xmltodict==1.0.4` requirement through its normal
dependency handling. Native Wake on LAN retains its own requirements and
network settings. Setup requests no NAS power action and sends no WOL packet.

## Assisted WOL

Confirm the physical MACs you intend to use, or enter them manually when QTS
identification is ambiguous. The assistant reuses matching native WOL entries.
For missing entries, select creation, review each interface's broadcast and
port, and confirm it explicitly. The summary distinguishes created, reused,
unavailable and skipped targets.

**Do not suggest again** is saved per NAS and can be reversed in Options.
Confirmed MACs automatically retain their matching associations. To detach an
interface, deselect its MAC and remove its selected native button. The native
entry remains under its owner's control.

The QNAP Power on button delegates to `button.press` on the associated native
buttons. With saved associations it also loads when the NAS is offline, after
the first bounded QTS connection attempt. A wake trial, shutdown or reboot
requires coordination with the owner. Record sending and observed recovery
separately.

## Power on availability and dashboard order

Power on stays visible and becomes temporarily unavailable while the QNAP
coordinator has confirmed QTS online. When QTS is unreachable, or monitoring
has no data yet after startup, it is available if all associated native WOL
targets are configured, enabled and loaded. Availability follows coordinator
updates and native-target changes. An unreachable QTS endpoint leaves the
physical power state unknown. Sending WOL requires an explicit press.

The native device page in frontend `20261028.5` sorts controls by name and
constructs its rows without a `confirmation` setting. A dashboard Entities
card can configure confirmation on its own rows and provides the order
Encender → Apagar → Reiniciar. These confirmations apply to this dashboard
card. The automatic device page exposes its own directly acting buttons.

Replace **both `button.reemplazar_id_*` markers** with the existing QNAP
Power on and Reboot entity IDs. The Shutdown ID below was confirmed for the
coordinated installation. Adapt it too when using another installation.
Row names are display labels. Entity identity, configuration and availability
continue to come from the existing entities.

```yaml
type: entities
title: Energía del NAS
show_header_toggle: false
entities:
  - entity: button.reemplazar_id_encender # Replace with the existing QNAP Power on ID
    name: Encender
  - entity: button.garaje_homenas_apagar
    name: Apagar
    confirmation:
      text: "¿Querés apagar el NAS?"
      confirm_text: Confirmar
      dismiss_text: Cancelar
  - entity: button.reemplazar_id_reiniciar # Replace with the existing QNAP Reboot ID
    name: Reiniciar
    confirmation:
      text: "¿Querés reiniciar el NAS?"
      confirm_text: Confirmar
      dismiss_text: Cancelar
```

`confirmation` sits alongside `entity` in each normal action row. Power on
acts directly. **Cancelar** closes the dialog without pressing the entity.
**Confirmar** makes one press on the row's existing button. Rows keep the
entity's current availability, including temporary unavailability.

To add the card, open an editable dashboard, choose **Edit dashboard → Add
card → Manual**, paste the YAML, replace the two markers and save. Find the
existing IDs in **Settings → Devices & services → Entities**. Configuration
and saving the card send no power request.

The row's confirmation and availability behavior is implemented in
[the frontend button row](https://github.com/home-assistant/frontend/blob/20261028.5/src/panels/lovelace/entity-rows/hui-button-entity-row.ts#L67).

## Roll back

Restore the previous `qnap` folder from the private backup and restart Home
Assistant. For a first installation, move the development component folder
out of `custom_components` and restart HA. Manage any entries through HA's
interface. Keep the existing configuration and registries.

Native WOL entries created with consent retain their configuration. Review or
remove them individually through **Devices & services** if desired. Reverting
the QNAP component preserves the global Python client used by the earlier
installation.

## Development packaging boundary

The ZIP carries unmodified client source under
`custom_components/qnap/_vendor/qnap_client`, with its MIT license. Only the
ZIP's integration imports point to that private namespace. The development
manifest uses `xmltodict` directly. This prevents an older globally installed
`qnap-client` with the same distribution version from satisfying the trial's
client requirement accidentally.

The repository's production imports and manifest retain the library-first
contribution structure. Distribution through a normal release will use the
maintainer's published client version. This ZIP is the coordinated trial
artifact. Physical NAS behavior and browser presentation remain live checks.

## Rebuild the artifact

From the integration checkout, with Python 3.12 or newer, run the following.
The client checkout must contain the pinned revision above.

```powershell
python .\tools\build_development_bundle.py --client-repo ..\python-qnap-power-pr --output ..\artifacts\qnap-assisted-wol-dev.zip
```

The builder reads committed source files and excludes private HA configuration,
diagnostics, virtual environments and local snapshots. Its output includes
the installation instructions and revision fingerprints.
