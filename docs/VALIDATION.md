# GuideGlass AI: testing and validation

## Scope and actual results

[Machine-readable software-check record](../tests/evidence/2026-10-16-software-checks.json) · This record contains actual software checks and explicit exclusions, not fabricated sensor data.

The offline suite covers geometry, pose math, worker/storage and loopback HTTP with deterministic synthetic fixtures and stubbed inference/devices, not real neural-model quality.

On 16 October 2026 the unchanged Python suite passed **49 tests in 7.71 seconds**. The Node frontend contract check also passed (DOM IDs, ten sensor formats, Arabic priority, late-speech callback and capture safety). These are not real Safari/audio/model-quality tests. [Dated runtime evidence](evidence/README.md) remains separate: bridge/camera HTTP 200, distance HTTP 502.

## Reproduce software checks

```powershell
python tools/check_docs.py
.\.venv\Scripts\python.exe -m pytest -q
node tests/frontend_contract.mjs
```

The documentation check needs only Python's standard library. Install the documented environment first. Tests use synthetic fixtures and stubbed inference/devices on local loopback. No paid endpoint, physical hardware or model download is needed for these tests.

## Error behavior to inspect

Tests cover bad calibration/depth, lost pose, duplicate timestamps, late results after stop, malformed maps, private-file access and Host/Origin boundaries. Geometry tests are not world-scale accuracy evidence.

## Hardware acceptance

Earlier camera transport succeeded; distance returned HTTP 502. No established root cause/fix, wearable ranging result, audible-effectiveness study, physical Safari validation or safe navigation result.

Collect board/sensor identity, traced wiring, known-distance samples, safe supervised recordings and physical Safari results. Record consent-aware accessibility trials only after they happen.

## Continuous integration

The proposed workflow runs documentation checks, Python tests and the Node contract check. It does not flash hardware, assess photo truth or establish safety. A workflow file is not a passing run; inspect Actions after an authorized push. No success badge is prefilled.

[Security](../SECURITY.md) · [Roadmap](ROADMAP.md)
