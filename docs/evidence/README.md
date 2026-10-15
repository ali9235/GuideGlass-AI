# Recorded operation—not a simulated demonstration

Evidence captured from the running Windows application on **15 October 2026**. The timestamp and observation details are in [runtime.json](runtime.json).

| Check | Recorded result | What it establishes |
| --- | --- | --- |
| Windows bridge | HTTP 200; ready | The application server responded. |
| Camera transport | HTTP 200; JPEG; 7,359 bytes | An image reached the bridge. It does not identify the board or establish frame rate. |
| Distance endpoint | HTTP 502; no valid reading | Physical distance measurement remains unverified. |
| Earlier software suite | 49 passed; no failures | Recorded software checks, not a hardware certification. |
| Speech control | Screenshot after a speech request | A request was made; audible output was not independently measured. |

![Real GuideGlass application](app-running.jpg)

The interface currently contains Arabic text. This is an actual screenshot, not an English mockup. Manual demonstration buttons are not object-detection evidence.

## Reproduce the capture

With the Windows server running and the intended device configured:

```powershell
.\.venv\Scripts\python.exe tools\capture_runtime_proof.py
```

The tool performs read-only requests and records status metadata without retaining camera pixels, credentials, LAN addresses, or personal filesystem paths in the JSON. A new run is a new observation—not permission to replace a failed result with an assumed success.

No assembled-glasses photograph, ultrasonic bench log, audible recording, or blind-user evaluation is included in this evidence set.
