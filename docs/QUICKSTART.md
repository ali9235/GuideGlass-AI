# Windows and iPhone quick start

## Windows

1. Install **Python 3.12** and open the project folder.
2. Run `setup_windows.bat`. It creates `.venv`, installs pinned dependencies and CPU PyTorch wheels, and downloads model/browser assets. Internet access and disk space are required.
3. Run `start_windows.bat` and open **http://localhost:8766/**.
4. Enter the intended LAN device address in the application. Check camera and distance status independently.

For a local-only session:

```powershell
.\.venv\Scripts\python.exe server.py --host 127.0.0.1 --port 8766
```

## iPhone Safari

On a trusted local network, start the normal Windows server and open `http://<Windows-LAN-address>:8766/` in Safari. Allow Windows Firewall access only on the appropriate private network. Both devices must reach that address, and Windows must stay running.

Tap the audio control before testing speech. Available voices depend on the device. Microphone capture and some browser features require trusted HTTPS; an HTTP viewer does not establish microphone support. The server supports configured `--tls-cert`, `--tls-key`, and explicit `--allow-host` options. Do not publish private keys or expose this unauthenticated research prototype directly to the public internet.

The current UI uses Arabic labels. Manual obstacle buttons are demonstrations, not detections.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Camera fails | Address, JPEG endpoint on port 80, network, and device firmware |
| Distance fails / HTTP 502 | `/distance` on port 82 and sensor firmware; do not substitute an invented reading |
| Missing 3D browser assets | Run `tools\prepare_assets.py --web` in the virtual environment |
| No speech | User interaction, voice/language, volume, browser support |
| Phone cannot connect | Windows process, private-network firewall, address, network isolation |

## Software checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node tests\frontend_contract.mjs
```

The JavaScript contract check requires Node.js. These checks do not actuate hardware or establish accessibility performance.
