# Isolated development testing

This procedure prepares a separate Home Assistant test instance. Execution of
the installation, account setup and real device actions requires coordination
with the owner. The existing Home Assistant instance and its configuration
remain under the owner's control.

## Current candidate state

| Component | Revision and state |
| --- | --- |
| Integration | `AVidal88/qnap-home-assistant`, branch `feat/qts-power-buttons` |
| Upstream base | `7630e0e03a255f9cdd35d109e2d50bc6666125d8` |
| Power button implementation | `45a65f958dfdb9e9f909f7e16d6f8a11248c483e` |
| Library candidate | `AVidal88/qnap-python-client`, commit `b2f467a7dc5899d748d901c1d7549436758429d6` |
| Power buttons | Candidate `shutdown()` and `reboot()` button implementation, subject to the reviewed integration commit |
| Reference test image | `ghcr.io/home-assistant/home-assistant:2026.11.1` |

Record the exact integration commit from the delivery, along with both checkout
hashes, before preparing an image. A branch name alone can move between reviews.
Offline tests exercise the integration code with mocked QTS communication.
Installation and real sensor/button behavior in Home Assistant remain pending
the coordinated trial described below. Historical library/diagnostic trials
provide their own evidence and do not establish HA acceptance.

The candidate's HACS minimum is 2025.3.0, based on the APIs it imports.
Offline integration tests use Home Assistant 2026.10.4 and Python 3.14.
Functional testing at the declared minimum and deployment in the reference
image below remain pending.

The library candidate retains distribution metadata `1.1.0`. Its source contains
the proposed power methods. The published package with that version identifies
the existing release. Package version alone therefore cannot establish that the
candidate code is installed. Development uses a wheel built from the exact
candidate checkout and verifies the imported source.

The ordinary integration manifest remains on its published dependency while
this development procedure is being prepared. Distribution of the final HA PR
requires the maintainer's published client release containing the methods and
an appropriate requirement update. The local development image is an explicit
source override.

The implementation creates an independent `QnapClient` for each button press,
using the entry's existing HTTPS and `verify_ssl` choices. Its public power
method sends the request. The control client closes locally without a logout
request, and the monitoring client retains its own session. Each monitoring
poll validates system identity through public reads and can renew an expired
session once. Empty or mismatched aggregate identity fails the update. A NAS
or session failure during an individual optional reading can still be masked
by the inherited library aggregate. General monitoring/parser improvements
remain separate.

## Reproduce the offline tests

Use Python 3.14 and a separate test environment for
`requirements_test.txt`. The helper pins HA 2026.10.4. From the reviewed
integration checkout, with `QNAP_CLIENT_SOURCE` pointing to the exact client
checkout above, run the following.

```bash
python3.14 -m venv .venv-test
. .venv-test/bin/activate
python -m pip install -r requirements_test.txt
PYTHONPATH="$QNAP_CLIENT_SOURCE:$PWD" python -m pytest -q
python -m ruff check custom_components/qnap/button.py \
  custom_components/qnap/coordinator.py custom_components/qnap/__init__.py tests
python -m ruff format --check custom_components tests
git diff --check
```

Pytest blocks network sockets and permits local Unix sockets for its event
loop. Tests load the custom integration in the HA harness and mock QTS
communication. The client source override selects the reviewed methods and
exception classes without changing the manifest or installing a fictional
release. Keep this environment separate from the client project's own
development dependencies.

The full-tree Ruff check also reports two inherited unused `SLF001` directives
in `switch.py` under Ruff 0.17.4. They are outside the button change and remain
recorded for a separate decision. The files changed for this candidate pass
their focused lint check.

The final local run passed 44 tests, four subtests and two snapshots in that
same suite on HA 2026.10.4 with the pinned client source override. Formatting
and diff checks passed. Focused Hassfest validators for JSON, manifest,
translations and config flow reported zero errors. The complete Hassfest
launcher could not start in this local harness because `infrared_protocols`
was absent. Full Hassfest and HACS CI validation remain pending.

## Prepare a dedicated workbench

The commands below use Bash on a Linux development host with Docker and Python
3.12 or newer for the pure-Python client wheel. Choose a host that remains
powered when the NAS is off. The owner supplies the reviewed integration commit
as `QNAP_HA_REVISION` before running this block.

```bash
set -eu
: "${QNAP_HA_REVISION:?Set this to the reviewed integration commit from the delivery}"

QNAP_DEV_ROOT="$PWD/qnap-ha-development"
QNAP_CLIENT_REVISION=b2f467a7dc5899d748d901c1d7549436758429d6
test ! -e "$QNAP_DEV_ROOT"
mkdir "$QNAP_DEV_ROOT"

git -c core.autocrlf=false clone --single-branch --branch feat/qts-power-api-pr \
  https://github.com/AVidal88/qnap-python-client.git "$QNAP_DEV_ROOT/client"
git -c core.autocrlf=false -C "$QNAP_DEV_ROOT/client" checkout --detach "$QNAP_CLIENT_REVISION"

git -c core.autocrlf=false clone --single-branch --branch feat/qts-power-buttons \
  https://github.com/AVidal88/qnap-home-assistant.git "$QNAP_DEV_ROOT/integration"
git -c core.autocrlf=false -C "$QNAP_DEV_ROOT/integration" checkout --detach "$QNAP_HA_REVISION"

git -C "$QNAP_DEV_ROOT/client" rev-parse HEAD
git -C "$QNAP_DEV_ROOT/integration" rev-parse HEAD
test -z "$(git -C "$QNAP_DEV_ROOT/client" status --porcelain)"
test -z "$(git -C "$QNAP_DEV_ROOT/integration" status --porcelain)"

mkdir "$QNAP_DEV_ROOT/image" "$QNAP_DEV_ROOT/test-config"
mkdir "$QNAP_DEV_ROOT/test-config/custom_components"
cp -a "$QNAP_DEV_ROOT/integration/custom_components/qnap" \
  "$QNAP_DEV_ROOT/test-config/custom_components/qnap"

python3 -m pip wheel --no-deps --wheel-dir "$QNAP_DEV_ROOT/image" \
  "$QNAP_DEV_ROOT/client"
```

The fresh-directory check prevents reuse of an existing HA configuration. The
image build context below contains the client wheel and Dockerfile. Keep
`test-config` outside that context, including after credentials have been
entered locally.

Create `Dockerfile` in the new `image` directory with this content.

```dockerfile
FROM ghcr.io/home-assistant/home-assistant:2026.11.1
COPY qnap_client-1.1.0-py3-none-any.whl /opt/qnap_client-1.1.0-py3-none-any.whl
RUN uv pip install --system --no-deps --reinstall /opt/qnap_client-1.1.0-py3-none-any.whl
```

The official image installs its dependencies with uv and includes aiohttp and
xmltodict. Installing the runtime wheel with `--no-deps` preserves those HA
dependency versions. The library's development extra belongs to its own test
environment. [Official image source](https://github.com/home-assistant/core/blob/2026.11.1/Dockerfile),
[image requirements](https://github.com/home-assistant/core/blob/2026.11.1/requirements_all.txt).

```bash
docker build --tag qnap-ha-power-test:development "$QNAP_DEV_ROOT/image"

docker run --rm -i --entrypoint python3 qnap-ha-power-test:development - <<'PY'
import hashlib
from importlib.metadata import version
from pathlib import Path

from qnap_client import QnapClient
import qnap_client.client as module

source = Path(module.__file__).read_bytes()
assert version("qnap-client") == "1.1.0"
assert callable(QnapClient.shutdown)
assert callable(QnapClient.reboot)
assert hashlib.sha256(source).hexdigest() == (
    "f859c066d77b3bcbebba369240fad5c0c3bf81cfb670940718adb5a340e7471b"
)
print("Candidate imports and committed source fingerprint verified")
PY
```

The fingerprint above belongs to the LF-normalized committed `client.py` at
the pinned revision. The earlier Windows working-file fingerprint
`3ec8b8b16c1dc1e6c02fa71683178597c5ed32794d364852b98dfc660adabd59`
belongs to its CRLF representation. The per-command Git setting above keeps
these fresh checkouts LF-normalized without changing global Git settings.

Home Assistant checks installed distribution versions before installing a
requirement. Preinstallation in this image occurs before HA starts. Verify
the source fingerprint on every new image. [Requirement handling](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/requirements.py),
[installed-package check](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/util/package.py).

## Start the isolated instance after coordination

Ensure that the container name and local port below are unused. The command
creates a distinct test instance and retains its separate configuration.

```bash
docker run --detach --name qnap-ha-power-test \
  --label qnap.power-test=isolated \
  --publish 127.0.0.1:8124:8123 \
  --mount "type=bind,source=$QNAP_DEV_ROOT/test-config,target=/config" \
  qnap-ha-power-test:development
```

Open `http://127.0.0.1:8124` from the development host and complete its own
onboarding. Use this test instance's Settings pages for integration setup.
When following a My Home Assistant link, confirm that it targets this instance.
The selected My HA URL can otherwise point to a different installation.

Container networking must be reviewed before WOL testing. Ordinary bridge/NAT
connectivity can permit QTS HTTPS polling while preventing the broadcast packet
from reaching the NAS. Docker Desktop and Linux host networking have different
behavior. Select a suitable network during coordination. The port mapping
above establishes access to the test UI and supplies no evidence of WOL reachability.

## Staged validation

### Connection and sensors

1. The owner creates the QTS account and enters its credentials only in the
   test instance's QNAP UI. Agree on authentication accepted by the library's
   public login flow. The historical interactive diagnostic adapter remains
   separate from HA.
2. Configure the real QTS host and port, HTTPS and the intended certificate
   verification choice. Retain verification by default. A deliberate choice
   to omit it belongs to that NAS configuration.
3. Verify identification and credible sensor values while the NAS is already
   on. Record which readings the account can access. Successful setup and a
   synthetic zero value have different evidential value.
4. Exercise reload/unload and controlled interruption/session-expiry cases
   before energy testing. Check recovery of fresh sensor data through the
   public library API. The current SDK aggregate can substitute defaults for
   failed reads, so acceptance must verify data recovery explicitly.

### Native Wake on LAN

The owner configures or explicitly selects the native WOL entries for the
NAS's verified physical interfaces. Follow the onboarding guide's MAC,
broadcast and connectivity instructions. Entry creation and packet sending
are separate from a demonstrated wake.

A voluntary wake test requires the NAS to be off under an independently
agreed procedure. Record the packet action separately from restored QTS
access and fresh QNAP sensor readings. Setup and discovery perform no power
test. Existing WOL entries for other devices retain their configuration.

### Energy buttons after explicit approval

Confirm that the checked-out integration commit contains both button entities
and that the imported library passed the source verification above. Record the
button entity IDs selected for this NAS before this stage.

Coordinate each real action separately. Verify one public `shutdown()` or
`reboot()` call per press, response classification, the UI error and subsequent
monitoring recovery. CGI acceptance and physical observation remain separate
results. The library clears its local SID after an energy attempt. HA therefore
needs a tested recovery path that restores monitoring without repeating energy.

Exercise permission rejection using an agreed account and coordinated test.
Verify that allowed monitoring remains usable when power permission is denied.
Record demonstrated rights per operation. Minimum privileges remain unverified
and account creation belongs to the owner.

## Rollback

Inspect the container label, image and mount path before stopping it. Confirm
that they identify this workbench's test container.

```bash
docker inspect qnap-ha-power-test
docker stop qnap-ha-power-test
docker rm qnap-ha-power-test
```

Keep the private test configuration and recorded revisions for review. The
existing HA instance remains separate. If a later coordinated trial uses an
existing instance, first take its normal backup and preserve the previously
installed QNAP component and library versions. Roll back by restoring those
reviewed versions and restarting HA. Preserve its configuration, device and
entity registries. Manage entries through the UI. Manual `.storage` edits and
global registry deletion are outside this procedure.

An existing Linux Core development environment can instead install the pinned
client wheel and launch its separate config directory with
`hass --config <isolated-config> --skip-pip-packages qnap-client`. Verify that
this CLI option exists in the exact Core version and verify imported source
before startup. This public package-specific override is local development
infrastructure. [Core CLI arguments](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/__main__.py).
