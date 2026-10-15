# Hardware and interface status

The intended wearable uses glasses, a camera, and an ultrasonic distance sensor. Exact part numbers, mounting details, power ratings, and physical GPIO assignments have not been established from an assembled-hardware photograph or schematic.

| Element | Evidence | Missing confirmation |
| --- | --- | --- |
| Glasses / mount | Owner's project description | Assembled photograph and mounting details |
| Camera device | Actual JPEG received | Board and sensor markings; matching firmware |
| Ultrasonic sensor | Intended hardware; software input exists | Model, electrical interface, wiring, valid samples |
| Windows computer | Recorded running application | No special performance claim is made |
| iPhone viewer | Browser viewer design | End-to-end physical sensor and audible-output test |

This is an evidence table, not a purchasing BOM. No battery, regulator, amplifier, or sensor module has been guessed.

## Implemented software interface

The bridge requests JPEG frames from `http://<device>:80/capture` and distance JSON from `http://<device>:82/distance`. The browser accesses `/api/frame` and `/api/distance` on Windows. These are software defaults, not proof that a device supplies both endpoints.

Distance examples: `{"distance_mm":750}` or `{"distance_cm":75}`. A bare number is interpreted as millimetres; explicit units are preferable. Missing, non-positive, or error-marked readings must not become a successful measurement. The browser requests a warning below 100 cm when audio and real warnings are enabled, at most once per seven seconds. These thresholds are not calibrated safe-clearance limits.

## Before connecting hardware

Confirm the exact board and sensor from markings and manufacturer documentation. Record actual power rails, logic levels, ground connections, and GPIOs before drawing a circuit. Validate known-distance stationary targets and disconnected/no-echo behavior before a supervised wearable trial.

One forward range value cannot establish a complete obstacle map or prove that an object is moving. No wiring diagram is supplied until the real connections are confirmed.
