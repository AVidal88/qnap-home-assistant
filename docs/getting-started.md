# Set up QNAP monitoring and power control

Use the QNAP integration for monitoring and the official Home Assistant Wake on
LAN integration for optional remote power-on. This development candidate adds
Shutdown and Reboot buttons, which still require coordinated device validation
inside Home Assistant. Their underlying library methods have been exercised on a TS-431P
running QTS 5.2.11.3661. Compatibility with other models and QuTS hero remains
unverified.

## Requirements

- Use Home Assistant 2025.3 or later for this candidate. This is the earliest
  checked release supplying its existing imported APIs. Functional validation
  of that minimum release remains pending. Native Wake on LAN configuration
  and its button have been available from Home Assistant 2024.8.
- Keep Home Assistant running on another machine if it must wake this NAS.
- Create and manage your QTS account yourself. Enter its credentials locally
  in the QNAP configuration form.

The QNAP minimum above follows its use of
`AddConfigEntryEntitiesCallback`. The preceding Home Assistant release lacks
that API. [Home Assistant 2025.3 source](https://github.com/home-assistant/core/blob/2025.3.0/homeassistant/helpers/entity_platform.py),
[Home Assistant 2025.2 source](https://github.com/home-assistant/core/blob/2025.2.0/homeassistant/helpers/entity_platform.py),
[Wake on LAN UI release announcement](https://www.home-assistant.io/blog/2024/08/07/release-20248/).

### QTS account and permissions

Minimum account permissions for monitoring, shutdown and reboot still need
separate validation. The successful library power trials used the NAS owner's
account. The QTS implementation checks administrator or delegated permissions.
The minimum usable role and the behavior of a monitoring-only account remain
unverified. Validate each operation with the account you intend to use before
relying on it. A denied power action should be assessed independently from
authorized monitoring. [Library evidence and permission limitations](https://github.com/AVidal88/qnap-python-client/blob/feat/qts-power-api-pr/docs/power-api-evidence.md).

The public library currently performs password login and reports a required
second factor. The local device trials used an interactive MFA adapter outside
the package. Completing that challenge through the Home Assistant integration
remains unsupported. Keep your existing MFA policy while choosing a supported
deployment approach. [Authentication trial boundary](https://github.com/AVidal88/qnap-python-client/blob/feat/qts-power-api-pr/docs/device-evidence/mfa-01.md).

## 1. Connect QNAP and check sensors

1. For this development candidate, coordinate the [isolated installation
   procedure](development-testing.md) using the reviewed integration and
   library commits. After the client release and manifest update, ordinary
   installations can use the [installation guide](../README.md#-installation).
2. Open **Settings → Devices & services → Add integration → QNAP**.
3. Enter the NAS hostname or IP address and the QTS administration port.
4. Enable **SSL** to use HTTPS. Choose the HTTPS port configured on your NAS,
   commonly 443. The form's default port is 8080, so check it explicitly.
5. Leave **Verify SSL certificate** enabled to check the certificate's trusted
   issuer, validity and match with the chosen hostname or IP address. An
   explicit decision to disable this option retains HTTPS encryption and omits
   those certificate checks. SSL and certificate verification are separate
   existing settings.
6. Enter your QTS username and password locally and finish setup.
7. Open the QNAP device and check that enabled sensors update. Enable any
   additional sensors you need through **Settings → Devices & services →
   Entities**. Many per-interface, drive and volume sensors start disabled.

Complete connection and sensor checks before scheduling any power tests. Use
**Reconfigure** on the QNAP entry to change connection settings later. Future
power actions use the same SSL and certificate-verification selection as that
entry.

## 2. Configure optional native Wake on LAN

Wake on LAN ships with Home Assistant. Open its official setup assistant and
follow the steps below. QNAP can operate with WOL absent, and WOL has its own
configuration entry. Configure this built-in integration directly from
**Settings**. [Open the Wake on LAN assistant](https://my.home-assistant.io/redirect/config_flow_start/?domain=wake_on_lan),
[official Wake on LAN documentation](https://www.home-assistant.io/integrations/wake_on_lan/).

### Prepare the NAS and network

1. Check WOL support for your exact NAS model and physical network port.
2. In QTS, open **Control Panel → System → Power → Wake-on-LAN (WOL)** and
   enable it manually. Check that EuP settings permit WOL. Keep AC power
   connected after shutdown so the network interface has standby power.
   [QTS 5.2 power settings](https://docs.qnap.com/operating-system/qts/5.2.x/en-us/power-506BFE6B.html).
3. Identify a physical interface MAC suitable for WOL. Confirm its cable and
   switch connection. Multiple interfaces or LACP may require testing individual
   ports. Bond MAC addresses, link-aggregation behavior and supported wake ports
   vary by model and network configuration.
4. Determine the broadcast address from the actual subnet mask and network
   layout. For a fictional `192.0.2.10/27` network, the subnet broadcast is
   `192.0.2.31`. Use your own network's values.
5. Check that UDP broadcast traffic can reach that interface from the machine
   running Home Assistant. VLANs, routers, firewalls and container networking
   can affect delivery. Choose the broadcast port required by your setup,
   commonly UDP 9. [Official WOL configuration fields](https://www.home-assistant.io/integrations/wake_on_lan/#configuration).

### Add or reuse the matching button

1. Inspect existing **Wake on LAN** entries in **Settings → Devices & services**.
   Reuse an entry whose MAC matches the intended NAS interface. Confirm the
   broadcast address and port in its options.
2. If a matching entry is needed, open the assistant above or choose **Add
   integration → Wake on LAN**. Supply the physical MAC, broadcast address and
   port, then finish the form.
3. Give its native button a recognizable name. For multiple intended physical
   interfaces, configure and label the required entries individually.

Configuration is complete before any button is pressed. Schedule a voluntary
wake test after monitoring works and a suitable shutdown has been coordinated.

### Understand the WOL state

| State | What it establishes |
| --- | --- |
| Available | Home Assistant includes the native integration |
| Loaded | Its component and actions are running |
| Configured for this NAS | A selected entry targets a confirmed physical MAC with appropriate broadcast and port |
| Wake verified | An authorized packet send was followed by observed NAS recovery |

The `wake_on_lan.send_magic_packet` action can be loaded on its own. A native
WOL button records a press and sends a packet. Its stateless behavior leaves
reception and NAS startup to be observed separately. During a coordinated wake
test, check the NAS becomes accessible and QNAP sensors resume updating. The
current monitoring coordinator polls every five minutes. Recovery after a power
action still needs validation in Home Assistant.
[Native WOL button behavior](https://www.home-assistant.io/integrations/wake_on_lan/#button),
[action-only configuration](https://www.home-assistant.io/integrations/wake_on_lan/#integration-services).

### Optional one-button action for several physical interfaces

In **Settings → Automations & scenes → Scripts**, create a script. Add the
**Button → Press** action and explicitly select the native WOL buttons for the
intended NAS interfaces. Save the script with a useful name. Each button keeps
its own configured MAC, broadcast and port. Running the script sends each
selected packet. Use it only for interfaces whose WOL behavior you have chosen
to test. The setup can be completed entirely through the interface.
[Home Assistant script editor](https://www.home-assistant.io/docs/scripts/),
[button action](https://www.home-assistant.io/integrations/button/#action-buttonpress).

## 3. Validate the QNAP power buttons after coordination

Open **Settings → Devices & services → QNAP → Devices** and select the NAS.
Its configuration controls include **Shut down** and **Reboot**. Confirm that
you are using the reviewed development candidate before testing them. Every
press requests one action through `QnapClient.shutdown()` or
`QnapClient.reboot()`. Requests have no automatic retries, and a simultaneous
press receives an action-in-progress error.

The buttons inherit the NAS monitoring availability. An offline NAS makes
them unavailable after a failed poll. Native WOL remains an independent
control. Power permission errors are shown for the action and leave the
monitoring session available for reads it is authorized to perform.

Coordinate each energy test separately after connection, sensors and the chosen
wake path are working. Record CGI acceptance and observed NAS availability as
separate results. An accepted response acknowledges the request. Shutdown
completion or a reboot availability cycle requires its own observation.

The library trials established physical shutdown followed by WOL recovery, and
reboot CGI acceptance followed by remotely observed loss and recovery of access
on the TS-431P with QTS 5.2.11.3661. These trials used the Python executor. HA
button behavior, permissions, expired-session handling and monitoring recovery
remain to be checked against a real NAS inside HA. Offline tests cover these
integration paths with mocked communication. Development installation uses
the exact local client candidate. A published `qnap-client` release containing
the methods and a matching manifest requirement are needed for distribution.
[Shutdown evidence](https://github.com/AVidal88/qnap-python-client/blob/feat/qts-power-api-pr/docs/device-evidence/shutdown-01.md),
[reboot evidence](https://github.com/AVidal88/qnap-python-client/blob/feat/qts-power-api-pr/docs/device-evidence/reboot-01.md).
