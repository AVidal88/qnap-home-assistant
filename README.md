# QNAP beta for HACS

**Test release 3.3.0-beta.2** for Home Assistant 2025.3.0 or newer.

This fork distributes the assisted native Wake on LAN integration from
`1d43964ac8b3464833022281cc0b195b58043c8e` and the exact client candidate
`b2f467a7dc5899d748d901c1d7549436758429d6` in `_vendor/qnap_client`.
The library and integration contribution branches keep their own history.

## Install through HACS

1. Make a normal Home Assistant backup before replacing an existing component.
2. In **HACS → menu → Custom repositories**, add
   `https://github.com/AVidal88/qnap-home-assistant` as **Integration**.
3. Open **QNAP (AVidal88 beta)** and **Download / Redownload**. Expand
   **Need a different version?**, choose a release and select **3.3.0-beta.2**
   before confirming. Some HACS versions also offer **Show beta versions**.
   If the initial version field shows a commit hash, change it to this beta.
4. Restart **Home Assistant**. Keep an existing QNAP configuration entry, or add
   QNAP in **Settings → Devices & services** if this is its first installation.

The release asset is `qnap.zip`. It contains `manifest.json`, the component
modules and `_vendor` directly at its root. HACS extracts those files into
`custom_components/qnap`. The fork's default branch is `distribution/hacs-beta`,
with matching `zip_release` metadata and a complete vendored component.
The download dialog hides the default branch, leaving explicit release selection.

## Existing upstream installation managed by HACS

Only one HACS repository should manage the `qnap` component directory.
Back up first. In HACS, remove the downloaded `disforw/qnap` repository, then
add this fork and download the beta before restarting HA. If HACS warns that
the integration is configured, choose **Ignore / Ignorar** to continue removing
the HACS package, then confirm removal. Keep QNAP in Devices & services.
HACS may remove the
component files during removal. The QNAP entry in **Devices & services** and
its device/entity configuration are kept under HA's own management.
Retain that entry and use the fork with the same `qnap` domain.

If the upstream repository is merely listed as available and has never been
downloaded, it has no installed component to transfer. Add and download the
fork normally. Review which repository is downloaded before future updates.

## Updates and rollback

Use **Update information** in the fork's HACS menu, then **Download / Redownload**
and select the next beta. Keep prereleases visible while following this channel.
Restart Home Assistant after changing the installed version.

For rollback within this fork, select **3.3.0-beta.1** in Download / Redownload
and restart HA. To return to upstream,
remove the fork through HACS, download `disforw/qnap`, and restart HA. The normal
HA backup remains another recovery option. Keep the QNAP configuration entry.
Native WOL entries created with consent retain their settings and can be managed
individually in Devices & services.

## What to check during the coordinated trial

Start with QTS login, NAS identity, credible sensors, the QTS buttons and reload
recovery. The optional assistant confirms physical MACs, reuses matching native
WOL entries and creates missing ones after per-interface consent. Options stores
associations and reversible per-NAS suppression of suggestions.

Power on delegates to the selected native WOL buttons. Saved associations also
load while QTS is unreachable, following the first bounded connection attempt.
It stays visible and becomes temporarily unavailable while monitoring confirms
QTS online. When QTS is unreachable or monitoring has no data yet, its
availability depends on the associated native WOL targets. An unreachable QTS
endpoint leaves the physical power state unknown. State changes update
availability, and WOL is sent only after an explicit press.
Shutdown and Reboot use the candidate client's public methods, one request per
press. CGI acceptance and the physical result are separate observations.
Coordinate any real wake, shutdown or reboot with the owner. Setup sends no
magic packet or power request.

The native device page in frontend `20261028.5` sorts controls by name.
An optional [Entities card example](docs/quick-install.md#power-on-availability-and-dashboard-order)
provides Encender → Apagar → Reiniciar, using the existing entities.

After a firmware update, the owner reported a native QTS shutdown that remained
off, successful recovery through this integration's Power on button and no new
improper-shutdown warning. The exact new firmware version is unconfirmed.
The recorded assessment is that the problem did not reproduce after updating
firmware. Shutdown from HA with that firmware remains for the next coordinated
trial. The earlier incidents retain their evidence and their cause is unknown.

## Distribution boundary

This beta includes the coordinator-based Power on availability change and the
same privately included client source. `SOURCE.json` records source revisions
and fingerprints. The flat package includes integration, SDK and icon licenses.
The manifest and packaging template use `xmltodict>=1.0.4` so the dependency can
follow Home Assistant updates. HA provides aiohttp.

Hassfest reports the known warning `Domain collides with built-in core integration`.
This fork retains the `qnap` domain to manage the existing QNAP entry and entities.

The existing offline tests covered native WOL coordination and offline startup
in HA 2025.3.0 and 2026.10.4. Live browser, network and NAS acceptance remain part
of the coordinated trial. This release does not publish a client package to PyPI.

HACS installation and removal behavior are documented in the
[HACS dashboard guide](https://www.hacs.xyz/docs/use/repositories/dashboard/).
The configured-integration warning is implemented in the
[HACS removal menu](https://github.com/hacs/frontend/blob/main/src/components/hacs-repository-owerflow-menu.ts#L117).

## Licenses and attribution

The integration is distributed under the [MIT license](LICENSE), as explicitly
declared in the upstream README in
[disforw/qnap commit fb30dad](https://github.com/disforw/qnap/blob/fb30dad905f9a5127c601eb3ad1a31a7c97dc0cc/README.md).
This distribution adds the standard license text and attributes the integration
to disforw and contributors. The inspected upstream history contains the MIT
declaration and its link to a missing license file.

The included Python SDK retains its own original
[MIT license and copyright notice](custom_components/qnap/_vendor/qnap_client/LICENSE).
The generic NAS icon has separate Apache-2.0 terms and source attribution in
[the brand notice](custom_components/qnap/brand/NOTICE.txt).

The original `3.3.0-beta.1` tag and release assets preserve that trial's package.
This beta includes the subsequent publication metadata and local brand assets.
