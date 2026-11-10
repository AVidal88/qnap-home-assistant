# NAS power control: research and design

Research date: 2026-11-10. This document records evidence, design boundaries, and a hardware acceptance plan. It is not a statement that NAS shutdown/restart has been implemented or validated.

## Revisions inspected

- Integration: [`disforw/qnap` at `7630e0e03a255f9cdd35d109e2d50bc6666125d8`](https://github.com/disforw/qnap/tree/7630e0e03a255f9cdd35d109e2d50bc6666125d8), branch `Core`.
- Client: [`disforw/python-qnap` at `4792a60e0175c6eda31e18474c245d98f926d681`](https://github.com/disforw/python-qnap/tree/4792a60e0175c6eda31e18474c245d98f926d681), branch `main`.

The work is developed on isolated local branches intended for forks. Remote fork ownership/existence must be confirmed before publishing branches. No upstream repository changes, published pull requests, or real NAS power actions are part of this investigation.

## Existing architecture and conventions

### Python client

The distribution is `qnap-client`; the import package is `qnap_client`. The inspected release declares version `1.1.0`, Python >=3.12, `aiohttp>=3.9.0`, and `xmltodict>=0.13.0`. Hatchling builds the package. Typed dataclasses describe system, CPU, memory, network, drive, volume, firmware, fan, external-drive, and container data. See [package configuration](https://github.com/disforw/python-qnap/blob/4792a60e0175c6eda31e18474c245d98f926d681/pyproject.toml) and [models](https://github.com/disforw/python-qnap/blob/4792a60e0175c6eda31e18474c245d98f926d681/qnap_client/models.py).

[`QnapClient`](https://github.com/disforw/python-qnap/blob/4792a60e0175c6eda31e18474c245d98f926d681/qnap_client/client.py) is asynchronous. It owns an `aiohttp.ClientSession` unless one is supplied. Login posts the username and base64-encoded password to `/cgi-bin/authLogin.cgi`; base64 is encoding, not encryption. XML `authPassed=1` and a nonempty `authSid` establish the session. Authenticated reads send `sid` as a query parameter. The client currently invalidates its SID on HTTP 401; that alone does not distinguish XML permission errors from session expiry. `logout()` clears the local SID even if the remote logout fails.

The read endpoints are `management/manaRequest.cgi`, `management/chartReq.cgi`, and `sys/sysRequest.cgi` for firmware information. `get_all()` collects sections concurrently and replaces failed sections with defaults. This preserves partial monitoring, but an all-failed refresh can look like a successful aggregate unless reachability is represented explicitly. A WOL feature must not treat those defaults as proof that the NAS is online.

[`ContainerStationClient`](https://github.com/disforw/python-qnap/blob/4792a60e0175c6eda31e18474c245d98f926d681/qnap_client/container_station.py) shares the client session and sends the QTS SID as a Bearer token to Container Station v3. Its executable methods use GET for listing and POST for actions. Some comments still describe an older CS cookie flow; executable behavior is the useful baseline. Container actions are distinct from host power operations and provide no evidence of a host shutdown API.

Security findings in the inspected baseline:

- Login writes the SID to a debug log.
- Raw transport exception strings may contain authenticated URLs.
- Container action errors include part of the response body, which must not be assumed safe to log.
- Caller logs can expose an exception's chained cause even if its public message is generic.

Any change to these paths needs tests for messages, logs, and traceback output using synthetic canary secrets. Passwords, encoded passwords, SIDs, tokens, cookies, authorization headers, and raw responses must not be emitted.

### Home Assistant integration

The custom integration uses config entries and a typed `runtime_data` coordinator, with sensor, switch, and read-only firmware-update platforms. [`QnapCoordinator`](https://github.com/disforw/qnap/blob/7630e0e03a255f9cdd35d109e2d50bc6666125d8/custom_components/qnap/coordinator.py) logs in during coordinator setup and polls every five minutes. Container Station failures are nonfatal. [`async_setup_entry`](https://github.com/disforw/qnap/blob/7630e0e03a255f9cdd35d109e2d50bc6666125d8/custom_components/qnap/__init__.py) currently requires the first coordinator refresh before forwarding platforms.

That setup ordering matters: making only a button's `available` property independent of the coordinator is insufficient. After Home Assistant starts while the NAS is off, the button would never be created if initial setup still requires QTS. The design must handle initial offline setup as well as later polling failures.

The UI config flow validates credentials online, uses the NAS serial as the unique ID, and supports reconfiguration. It has no WOL options in the inspected baseline. Existing entities use `CoordinatorEntity`, device identifiers `(DOMAIN, unique_id)`, stable unique IDs, `_attr_has_entity_name`, and sensor translation keys. Most per-device sensors default to disabled. English is the existing translation language. New button names and configuration errors should use translation keys; an English string must not be hard-coded into entity logic.

The [manifest](https://github.com/disforw/qnap/blob/7630e0e03a255f9cdd35d109e2d50bc6666125d8/custom_components/qnap/manifest.json) pins `qnap-client==1.1.0`. It declares local polling and a device integration. The HACS metadata's old minimum Home Assistant version is not evidence that all APIs used by the current rewrite are supported there. The actual minimum must be validated against the chosen Home Assistant test/runtime version.

### Existing validation

- The client has pytest tests using `pytest-asyncio` and `aioresponses`. CI installs `.[dev]` and runs `pytest tests/ -v` on Python 3.12 and 3.13. Its XML samples exercise parser behavior; they do not establish firmware compatibility or the power API contract.
- Integration tests under `tests/components/qnap` retain Home Assistant core imports and mocks of the older `QNAPStats` interface. Those tests need a runnable custom-component harness before their result can validate the rewritten `qnap_client` integration.
- Integration workflows run Ruff check/format, Hassfest, and HACS validation, targeting `Core`. They do not run an integration pytest suite in the inspected baseline.
- Local unit tests, dependency checks, package builds, workflow execution, installed Home Assistant behavior, and physical NAS acceptance are separate results. Passing one must not be reported as passing another.

## Existing issues and related work

The issue and PR searches were read-only. No maintainer acceptance is assumed.

- [Integration issue #21: native power controls](https://github.com/disforw/qnap/issues/21) proposes three buttons and a library-first API contribution. It reports a TS-431P on QTS 5.2.x waking after full shutdown with 802.3ad LACP, including a separate switch/client restart. This is the reporter's hardware observation, not a test performed during this contribution or a cross-model support guarantee. There were no comments when inspected.
- [Integration issue #20: QTS 5.2.10 decoding failure](https://github.com/disforw/qnap/issues/20) reports setup failure on a TS-230 using a delegated System Monitoring account. This is evidence against claiming all QTS 5.2 devices work without additional fixtures.
- [Integration issue #14: MFA](https://github.com/disforw/qnap/issues/14) tracks missing MFA support. The current client sends username/password only. Do not infer from that limitation that QTS itself lacks all two-step authentication APIs, or recommend weakening an existing administrator account.
- [Integration issue #17: NIC keys](https://github.com/disforw/qnap/issues/17) reports nonuniform NIC data; [issue #18](https://github.com/disforw/qnap/issues/18) reports duplicate-device identification. Neither should be expanded into an unrelated parser/identity rewrite within WOL work.
- [Client issue #1: QuTS hero h5.2.10](https://github.com/disforw/python-qnap/issues/1) reports successful login/system information but missing or incorrect health, memory, fan, disk, volume, and network data. It also reports `authPassed=0` for a delegated account on a chart endpoint. Treating that value universally as an expired SID would create repeated logins without solving permissions. Sanitized real fixtures are offered in the issue, but none were supplied to or tested by this investigation. There were no comments when inspected.
- The integration's [historical coordinator PR #8](https://github.com/disforw/qnap/pull/8) explains the move to a dedicated coordinator. PR searches found no existing power implementation in either upstream repository. This is a search result, not a claim that no external implementation exists.

## What QNAP documentation establishes

### Wake-on-LAN

The official [QTS 5.2 power guide](https://docs.qnap.com/operating-system/qts/5.2.x/en-us/power-506BFE6B.html) and [QuTS hero h5.2 guide](https://docs.qnap.com/operating-system/quts-hero/5.2.x/quts-hero5.2.x-ug-en-us.pdf) describe WOL under Control Panel > System > Power. EuP disables WOL. They also warn that disconnecting power while the NAS is off can prevent WOL until a manual boot.

QNAP's [WOL ports FAQ](https://www.qnap.com/en-au/how-to/faq/article/which-ports-are-used-on-qnap-nas-for-wake-on-lan), modified 2026-01-06, covers QTS and QuTS hero, identifies UDP 9 and 40000, and explains broadcast/network/model requirements. Therefore use configurable destination and port, with UDP 9 as the conventional default. Sending a packet proves only local transmission, not delivery or boot.

The official [Qfinder presentation](https://www.qnap.com/s3/qutube/slides/p8j5gKt9n9A.pdf) allows entering a MAC directly and warns about model/NIC support. Its 10GbE warning should prompt checking the exact model/adapter specification; it is not a universal statement about every present or future 10GbE adapter.

The [QTS trunking guide](https://docs.qnap.com/operating-system/qts/5.2.x/en-us/lan-switching-configuration-29A9410.html) describes logical aggregation and switch requirements. It does not guarantee wake behavior after LACP negotiation stops. No verified QNAP contract was found establishing that an aggregate MAC identifies every physical wake-capable NIC.

### Shutdown, restart, and permissions

The official [QTS 5.2 task-bar guide](https://docs.qnap.com/operating-system/qts/5.2.x/en-us/task-bar-33FA3D49.html) describes an orderly QTS shutdown followed by power-off, and a separate restart action. This confirms product behavior, not HTTP method, endpoint, parameters, response codes, or ordering guarantees for third-party callers.

The official [delegated administration guide](https://docs.qnap.com/operating-system/qts/5.2.x/en-us/delegated-administration-87EDB7A6.html) distinguishes System Monitoring from broader System Management. It does not specify which delegated role may invoke a host power CGI action. Do not equate valid login or a readable monitoring endpoint with permission to stop the NAS. Do not assume only the default `admin` account can perform the action either.

A [QNAP-hosted authentication PDF v5.1.0](https://eu1.qnap.com/dev/QTS_HTTP_API-Authentication_v5.1.0.pdf) is linked by external clients, but could not be retrieved during this investigation. Its title and link are not evidence of its current contents. Existing client source proves how this project authenticates; it does not prove all current QTS authentication modes are supported.

## Candidate power endpoint and evidence gap

The original source of [`mkch/qnap-tool`](https://github.com/mkch/qnap-tool/blob/227b85b92ed1ad1c927ec5d48fdeefb6f2430e74/qnap/qnap.go) shows:

1. POST username and encoded password to `/cgi-bin/authLogin.cgi`.
2. Parse XML `authPassed` and `authSid`.
3. POST to `/cgi-bin/sys/sysRequest.cgi` with query fields `sid`, `subfunc=power_mgmt`, and `apply=shutdown`.
4. Check HTTP 200 and XML `authPassed`.

This is direct source evidence for an existing third-party implementation. It is not vendor documentation or a captured QTS 5.2 response. In particular, `authPassed=1` may confirm authentication without confirming that shutdown was accepted. No verified response schema or QTS/hero firmware matrix accompanies that code.

Other examples do not close the gap. For example, [`ups-guard`](https://github.com/wtj-0527/ups-guard/blob/c34f747b71c84d482e73a0a186c08279d8f2debd/backend/src/hooks/qnap_shutdown.py) advertises both shutdown and reboot but its executable path always sends shutdown and treats HTTP 200 as sufficient success. Copying that code would invent support. Search results for alternative `power.cgi` paths likewise lacked a verified contract.

No sufficiently verified restart request, action value, permission failure response, accepted response, or firmware-specific contract was found. **Shutdown/restart methods and buttons must remain unimplemented until that evidence is obtained.** A placeholder button that always errors would suggest a supported function and is not an acceptable substitute. Do not send speculative power parameters even as a probe.

## Chosen design boundary

### WOL belongs in the integration

Use a native Home Assistant button for wake. It represents a momentary command, not a persistent power state; this follows the [HA button model](https://developers.home-assistant.io/docs/core/entity/button/) and existing [HA WOL behavior](https://www.home-assistant.io/integrations/wake_on_lan/). Reuse the established WOL dependency/protocol rather than add QTS-specific networking to `qnap-client`. The Python API library remains responsible for authenticated NAS operations.

Persist manual WOL settings in config-entry options:

- One or more physical NIC MAC addresses, normalized and deduplicated.
- An explicit IPv4 broadcast destination; default `255.255.255.255`.
- UDP destination port; default `9`, valid range 1-65535.

Manual physical MACs are deliberate: chart/sysinfo data may expose virtual, renamed, or aggregate interfaces, may be incomplete, and cannot be refreshed while the NAS is off. Automatic suggestions can be a later enhancement only if users can verify and override them. For multiple NICs, send a packet for every configured physical MAC. For NICs on different subnets, one broadcast destination may not be sufficient; configure a reachable destination or document that limitation rather than silently claim multi-subnet discovery.

The wake button must be created for an already-configured NAS when HA starts offline, remain available during QTS polling/authentication failures, and read only persisted WOL settings. It must not log in, ping, refresh QTS, or require live network metadata when pressed. Without configured MACs, omit the button or keep it unavailable with a clear configuration path. A configured button reports transmission errors as translated action errors; successful transmission does not claim the NAS is running.

Keep normal telemetry entities unavailable while there is no successful data refresh. Do not populate fake online readings to satisfy setup. Recover normal polling when QTS returns; represent credential failures separately. Release HTTP sessions on unload and failed setup. Options changes must preserve NAS credentials and trigger an orderly entity reload.

### Future API actions belong in the client

After a real contract is established, add explicit async shutdown and restart methods to `QnapClient`, then expose native HA buttons. Preserve existing monitoring and Container Station behavior. Use QTS's orderly mechanism, never a relay, smart plug, forced command, or undocumented force flag.

Each press may submit at most one destructive request. No automatic replay after timeout, transport loss, XML authentication rejection, HTTP 401/403, reauthentication, or HA refresh. Authentication can be established before submission, but failure after submission cannot trigger retry. Disable redirect following for the action request and audit library/middleware retry behavior. Serialize competing power actions so shutdown and restart cannot overlap.

Future availability should require online QTS plus verified permissions/capabilities; if those cannot be discovered read-only, keep actions disabled by default and document manual enablement and rejection behavior. `isAdmin` is useful evidence when present, but is not a complete permission model for delegated accounts. Restart can use HA's restart button device class; shutdown and wake should use names/icons with correct semantics. Both action errors and entity labels require translations.

## Dependency and release boundary

The working contribution may target `qnap-client==1.1.1` for transport/logging changes. That version is a **local unreleased candidate** until the maintainer publishes it. A version string or successful editable install is not proof that PyPI provides the release. Do not publish a tag or package as part of this work.

For local cross-repository validation, install the edited client from the adjacent checkout (for example `python -m pip install -e ../python-qnap`) into the same isolated environment as the integration tests. Record the installed module path and version, run `python -m pip check`, and ensure the HA test harness does not replace it with the published `1.1.0`. A manifest pin to an unpublished `1.1.1` is a dependency coordination item and is not ready for ordinary HACS installation until the release exists.

The library's Python >=3.12 floor is necessary but does not alone establish compatibility with a current HA release or its dependency constraints. Validate against the chosen HA version and supported Python interpreter. Do not claim that testing one interpreter reproduces the client's full 3.12/3.13 CI matrix.

## Physical acceptance plan

No real NAS shutdown or restart has been authorized for this contribution. The following plan describes future work, not completed tests.

### Read-only preparation

1. Record exact NAS model, NIC/adapter models, QTS or QuTS hero version/build, HA version, network topology, VLANs, LACP mode, and switch configuration. Keep public evidence anonymized.
2. Inspect WOL/EuP settings and physical NIC MACs in QTS. Do not change NAS settings implicitly. Confirm the configured interfaces support WOL according to the model/adapter specifications.
3. Verify credentials and permitted read-only calls for a dedicated monitoring account and a separate authorized administrator where available. Do not create users, escalate privileges, disable MFA, or change permissions solely to make a test pass.
4. Inspect the installed QTS UI's static power-action code if safely accessible. Reading static assets is distinct from pressing a control. Do not call the candidate endpoint with guessed or incomplete action fields.
5. In local packet-capture or loopback tests, verify magic-packet bytes, broadcast destination, port, each configured MAC, duplicate normalization, malformed-option rejection, and socket error handling without addressing a physical NAS.
6. With the NAS already off through a separately authorized workflow, check that HA startup/reload still exposes the configured wake button and that ordinary sensors remain unavailable. Sending a real wake packet should also be coordinated with the NAS owner; local unit tests must mock transmission.

### Power tests require separate explicit authorization

Before any real shutdown or restart, obtain the owner's explicit authorization for the exact NAS, action, and test window. Ensure no firmware update, replication, storage repair, active VM, or other workload makes the action inappropriate. That decision belongs to the operator; code must not invent an override.

For an authorized test, observe one intentional action in QTS's own UI first. Capture the method, path, parameter names and action value, relevant response content type/status/body structure, and whether acceptance precedes disconnect. Do not infer a restart value from the shutdown value. Record how a non-default administrator and relevant delegated roles behave. Permission-denied tests must use accounts known to be denied, rather than hope an unverified action will be harmless.

Do not export or commit raw HAR files, browser profiles, cookies, authenticated URLs, or complete logs. Create a minimal sanitized fixture that preserves structure and codes while replacing SID, qtoken, cookies, authorization values, passwords/encoded passwords, usernames, host/IP, serial, MAC, and other identifiers. Inspect the sanitized text manually and search for canary/known secret fragments before sharing. Store only sanitized evidence with explicit model/firmware provenance and the observation date.

After the request contract is established, test the library once per authorized action and observe the QTS shutdown/restart sequence. Separately confirm post-boot monitoring recovery. A disconnect cannot prove an orderly shutdown; verify the device's own health/logs on return and distinguish a completed operation from a merely accepted request.

### Required contract and error matrix

These are future acceptance criteria, not invented QTS response samples.

| Case | Evidence needed | Required client/HA behavior |
|---|---|---|
| Valid login | Actual successful response with credentials sanitized | Store a usable SID; do not log it |
| Wrong credentials / 2SV challenge | Actual response for that authentication mode | Authentication error; no power request |
| Monitoring-only account | Actual endpoint response or a verified read-only capability result | Permission error; preserve monitoring; no escalation/replay |
| HTTP 403 | Capture establishing meaning for this endpoint | Surface refusal separately from connectivity; never retry the action |
| HTTP 401 / expired SID | Status and/or XML proven to mean expiry | Clear unusable authentication where appropriate; no replay after submission |
| XML `authPassed=0` | Distinguish denial from expired authentication using captured evidence | Do not assume every XML rejection means expiry; no login loop |
| Accepted shutdown/restart | Explicit endpoint-specific acceptance schema | Report accepted command only; do not claim completed shutdown |
| HTTP 200 with malformed/unknown body | Sanitized response/negative test | Protocol error or indeterminate outcome; never success by status alone |
| HTTP 4xx/5xx | Endpoint-specific rejection examples | Sanitized error; no body/URL secrets; no automatic retry |
| Failure before submission | Transport instrumentation/local test | Connectivity error; do not claim acceptance |
| Disconnect/timeout after possible submission | Controlled local fault test and, if authorized, observed hardware behavior | Outcome indeterminate; explain that the NAS may be stopping; never replay |
| Concurrent button presses | Local concurrency test | At most one in-flight host power command |
| NAS offline at HA start | HA startup with existing entry and persisted WOL settings | Wake available; telemetry unavailable; later polling recovers |
| LACP and multiple NICs | Per-physical-port/model observation with network details | Record the tested configuration only; do not generalize to all bonds |

## Recommended contribution sequence

1. **Client security/transport correction:** remove session logging, sanitize exception and response propagation, distinguish HTTP/authentication failures conservatively, and test logs/tracebacks and session cleanup. Keep this independently reviewable and avoid unrelated parser changes. Coordinate a client release before changing a distributed integration pin.
2. **Integration offline lifecycle and WOL:** add persisted manual options and one wake button; make startup/reload and QTS-offline availability correct; add a runnable custom-component test harness, translations, documentation, and offline/error tests. Reference issue #21 and clearly state packet-level versus physical verification.
3. **Client host power API, then HA shutdown/restart buttons:** proceed only after sanitized real request/response evidence establishes each action, permissions, authentication, and ambiguity handling. Include fixture provenance and model/firmware limits; release the library before updating the integration requirement.
4. Keep broader hero parsing, missing sensors, identity issues, and MFA work in separate contributions unless a minimal prerequisite is demonstrated. Link the relevant existing issues and request the offered sanitized hero fixtures when communication is separately authorized.

No PR should describe all three controls as complete while the shutdown/restart contract remains unverified. A tested, documented WOL contribution plus an explicit follow-up plan is preferable to exposing destructive controls backed by assumed API responses.