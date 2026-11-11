# Power-control contribution: validation and delivery

Initial WOL milestone: 2026-11-10. At that point no real NAS was contacted
during development and no remote branches were published. Since then both
`feat/power-control` branches and a focused client API branch have been pushed
to the owner's forks. The owner's first authentication-only diagnostic against
the TS-431P returned `QnapAuthError` before any preflight GET. MFA is suspected
but not yet confirmed from response flags. No shutdown or restart command has
been sent and no PR, package, or tag has been published.

## Delivered scope

Implemented a native Home Assistant Wake-on-LAN button with offline options for
multiple physical MAC addresses, one IPv4 broadcast destination, and UDP port.
Configuration normalizes/deduplicates MACs, rejects invalid/multicast/zero MACs,
and permits removal by clearing the list. WOL runs in the executor and reports a
translated transmission failure without exposing the underlying exception.
It reports a press, never an assertion that the NAS has booted.

Existing entries now load while QTS is unreachable or authentication fails. The
wake button remains usable. Sensors and container switches are added only after
the first successful data update, without synthetic online data. Scheduled polling
recovers automatically. Unload stops scheduling and releases owned HTTP resources
without a logout request to an unavailable NAS. Firmware device naming retains the
entry title when QTS has not supplied live data.

The client removes session logging and raw response/transport error propagation,
normalizes HTTP 401/403, timeout and connection loss, disables redirects, and adds
idempotent close with externally owned sessions preserved. A rejected Container
Station request does not invalidate a QTS monitoring session. Failed system-info
reads now fail get_all instead of returning an apparently successful empty NAS;
optional section failures retain the existing partial-data behavior. Such defaults
remain a known monitoring limitation, not verified firmware support.

**Shutdown and restart buttons remain unimplemented in this integration.** The
official TS-431P-family QTS 5.2.11.3661 web client later established the request
shape, and [draft library methods](https://github.com/AVidal88/qnap-python-client/tree/feat/qts-power-api)
now exist. Their actual response, permissions, and physical behavior remain
unverified; QuTS hero compatibility is also unknown. See
[research](power-control-research.md) and the
[client evidence](https://github.com/AVidal88/qnap-python-client/blob/feat/qts-power-api/docs/power-api-evidence.md).

## Repositories and branches

- Integration base: disforw/qnap Core at 7630e0e03a255f9cdd35d109e2d50bc6666125d8.
- Client base: disforw/python-qnap main at 4792a60e0175c6eda31e18474c245d98f926d681.
- Both original local checkouts remain on `feat/power-control`; integration
  commit `19be179` and client commit `373f225` are preserved and match the
  published fork branches. The focused client worktree uses `feat/qts-power-api`.
- Integration `origin`: [AVidal88/qnap-home-assistant](https://github.com/AVidal88/qnap-home-assistant);
  client `origin`: [AVidal88/qnap-python-client](https://github.com/AVidal88/qnap-python-client).
  Each `upstream` fetches from the corresponding `disforw` repository and has
  its push URL disabled. No PR has been opened.

## Dependency boundary

The original client `feat/power-control` candidate uses version 1.1.1. The
focused API branch retains upstream package version 1.1.0 for maintainer review;
its local wheel is not a published release. The integration manifest still pins
`qnap-client==1.1.1` plus `wakeonlan==3.3.0`. Version 1.1.1 is not on PyPI,
so this HA branch is not ready for ordinary HACS installation or a distributable
PR. After the library PR is merged and a new release is published, update the
manifest to that actual version and re-run the HA tests. No package was uploaded.

Integration testing uses Python 3.14.10, Home Assistant 2026.10.4, and
pytest-homeassistant-custom-component 0.13.375 on Linux/WSL. The HACS minimum is
conservatively updated to the tested HA 2026.10.4 baseline. Older versions have
not been validated; the old 2024.1 declaration was inconsistent with the modern
APIs already used by the integration.

Client dev dependencies cap aiohttp below 3.14 because aioresponses 0.7.9 cannot
construct aiohttp 3.14 responses (upstream aioresponses issue #289). This cap is
only in the dev extra. Production keeps aiohttp>=3.9.0. A separate real HTTP
loopback suite validates aiohttp 3.14.5 without that mock dependency. No endpoint
or response used by those tests is claimed to originate from QTS firmware.

## Initial milestone validation results

The table records the earlier WOL milestone. The focused library branch has
since passed 57 local tests and built a wheel; its synthetic responses do not
establish QTS device compatibility. A current HA re-run remains pending because
the available HA test environment is incomplete and a clean Windows environment
could not resolve its Home Assistant package.

| Check | Environment | Result |
| --- | --- | --- |
| Client full pytest tests -q | Windows Python 3.12 / aiohttp 3.13.5 | 61 passed |
| Client full pytest tests -q | Linux Python 3.13.18 / aiohttp 3.13.5 | 61 passed |
| Client pytest tests/test_http.py -q | Windows Python 3.12 / aiohttp 3.14.5 | 4 passed |
| Integration pytest -q | Linux Python 3.14.10 / HA 2026.10.4 / aiohttp 3.14.5 | 38 passed |
| Client dependency check | Both Windows environments and Linux 3.13 | Passed |
| HA uv pip check | Linux Python 3.14.10 | Passed |
| Integration Ruff check and format | custom_components and tests | Passed |
| Client Ruff E4,E7,E9,F,I and format | package + new tests; format changed modules only | Passed |
| git diff --check | Both repositories | Passed |
| Client wheel build | Local qnap_client-1.1.1 wheel | Passed |
| Official Hassfest | core tag 2026.10.4, commit 357cae5c598dfcd7a0ea7dc5b1facccd4ec6037b | 1 integration, 0 invalid |
| HACS action | Docker Linux daemon unavailable | Not executed |
| Remote CI | No PR/workflow dispatch at this milestone | Not executed |
| Physical QTS 5.2 / QuTS hero | No device calls or power authorization at this milestone | Not executed |

Hassfest emitted one expected warning: the qnap domain collides with the built-in
core integration. It was run locally using the official script, installed HA
resources, and its normal custom-integration checks; this is not a GitHub Actions
run or confirmation that the unpublished client is available on PyPI.

The 4 aiohttp 3.14 transport tests are also part of the 61-test suite in its other
environments; do not add these counts as distinct tests or claim hardware coverage.
Integration sockets are disabled (Unix sockets allowed for HA internals), and every
QTS client and WOL transmitter is mocked. Client HTTP tests bind only 127.0.0.1.

Coverage includes missing temperatures, disappearing NICs, firmware updates,
connection/auth failures at startup and later, offline WOL presses, multiple MACs,
custom broadcast/port, invalid settings, clearing options, initial config and
reconfigure identity checks, secret canaries in logs/tracebacks, real polling timer
recovery, unload/reload cleanup and stable entity IDs. Client tests exercise status
mapping, redirects, interrupted requests, timeouts, caller-owned sessions, login
failure cleanup, partial reads, and Container Station auth isolation.

## Changed files

Integration:

- custom_components/qnap/__init__.py: offline setup and cleanup.
- custom_components/qnap/button.py: independent wake button.
- custom_components/qnap/config_flow.py: offline options and safe validation logs.
- custom_components/qnap/const.py: WOL defaults and key.
- custom_components/qnap/coordinator.py: lazy authentication, safe errors, close.
- custom_components/qnap/sensor.py and switch.py: add entities after real data.
- custom_components/qnap/update.py: preserve the device name offline.
- custom_components/qnap/manifest.json: exact client and WOL requirements.
- custom_components/qnap/strings.json and translations/en.json: options/action text.
- hacs.json: tested minimum HA version.
- tests/components/qnap/conftest.py: current dataclass/AsyncMock harness.
- tests/components/qnap/test_sensor.py and test_update.py: migrated regressions.
- tests/components/qnap/test_button.py, test_config_flow.py, test_lifecycle.py:
  offline, options, flows, polling and reload tests.
- tests/components/qnap/fixtures/qnap_data.json and snapshots/test_update.ambr:
  removed unused legacy fixtures/snapshots for the deleted QNAPStats interface.
- pyproject.toml, requirements_test.txt, .github/workflows/tests.yaml: reproducible
  custom-integration testing and future CI after the client release.
- .gitignore: generated test/runtime caches.
- README.md, docs/power-control-research.md, docs/power-control-validation.md:
  usage, evidence, limitations and hardware acceptance plan.

Client:

- qnap_client/client.py: sanitized shared transport, session lifecycle, required read.
- qnap_client/container_station.py: shared transport, safe errors, auth isolation.
- qnap_client/exceptions.py and __init__.py: exported permission error/version.
- pyproject.toml: version and test-tool dependency constraint.
- tests/test_transport.py and tests/test_http.py: synthetic transport/security tests.
- README.md and CHANGELOG.md: behavior, test commands and unreleased status.

## Physical acceptance still needed

1. Record exact model, firmware/build, NICs, broadcast topology and WOL/EuP settings.
   Confirm HA is hosted independently of the NAS and can reach its broadcast subnet.
2. With a separately authorized shutdown already complete, start/reload HA while
   the NAS is off; verify wake exists and telemetry is unavailable. Press wake once,
   verify boot and later polling recovery. Test each configured physical MAC and
   actual LACP switch arrangement; do not extrapolate to every NIC/model.
3. Test transmission failures and NAS unreachability. A successful UDP send is not
   proof of power-on. One broadcast destination per NAS is the current limit.
4. Only after explicit authorization for a named device/action/window: capture a
   single deliberate shutdown/restart from the official QTS UI. Collect sanitized
   request/acceptance/denial/expiry evidence with exact firmware provenance.
   Do not export raw HAR, cookies, SIDs, passwords or authenticated URLs.
5. Refine the draft host-power methods only when the remaining contract is established.
   Validate monitoring-only vs administrator/delegated permissions, expired sessions,
   errors, and ambiguous post-send disconnects with no replay. Repeat on hero before
   claiming hero compatibility. Never use forced power removal.

## Suggested PR sequence

1. First PR against `disforw/python-qnap`: validate and submit the focused
   shutdown/reboot API, with only necessary transport/security fixes and clear
   firmware limitations. The maintainer explicitly requested this order.
2. Second PR against `disforw/qnap`: combine the preserved offline WOL work with
   shutdown/reboot buttons, options, translations, and tests after the client
   release is available. Keep parser/hero/full-MFA work separate unless required.

Do not title or describe the current contribution as complete three-action power
control. It delivers software-tested WOL and prerequisites, with explicit unfinished
shutdown/restart work and no claim of physical compatibility.
