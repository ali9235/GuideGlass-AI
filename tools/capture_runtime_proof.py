"""Capture non-sensitive runtime evidence; never store camera pixels or LAN addresses."""
import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def capture(base_url):
    opener = build_opener(ProxyHandler({}))

    def get(path):
        try:
            with opener.open(base_url.rstrip('/') + path, timeout=8) as response:
                data = response.read(5000001)
                if len(data) > 5000000:
                    raise ValueError('Response exceeded evidence limit')
                return response.status, data, response.headers.get_content_type()
        except HTTPError as error:
            return error.code, b'', None
        except (URLError, TimeoutError, OSError):
            return None, b'', None

    status, raw, _ = get('/api/status')
    bridge = json.loads(raw) if status == 200 else {}
    camera_status, camera_raw, camera_mime = get('/api/frame')
    camera = {'http_status':camera_status, 'image_received':False}
    if camera_status == 200 and camera_mime and camera_mime.startswith('image/'):
        from PIL import Image
        with Image.open(io.BytesIO(camera_raw)) as image:
            image.verify()
        camera.update(image_received=True, format=camera_mime, received_bytes=len(camera_raw))
    sensor_status, sensor_raw, _ = get('/api/distance')
    sensor = {'http_status':sensor_status, 'valid_distance_received':False,
              'physical_sensor_type_verified':False}
    if sensor_status == 200:
        data = json.loads(sensor_raw)
        if isinstance(data, dict):
            for key in ('distance_mm','distance_cm','mm','cm'):
                if (key in data and isinstance(data[key],(int,float)) and 0 < data[key] < 10000
                        and data.get('valid') is not False and data.get('status') not in ('invalid','error')):
                    sensor.update(valid_distance_received=True, value=data[key], unit='mm' if key.endswith('mm') else 'cm')
                    break
    report = {'captured_at_utc':datetime.now(timezone.utc).isoformat(),
              'method':'Read-only requests to the running local GuideGlass server',
              'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'bridge':{'http_status':status,'state':bridge.get('bridge'),'device_configured':bool(bridge.get('ip'))},
              'camera':camera, 'distance_sensor':sensor,
              'scope':'Software operation and camera transport. No claim of an end-to-end ultrasonic hardware test.',
              'privacy':'No images, LAN addresses, credentials, or personal filesystem paths included.'}
    junit = ROOT / '.data/reports/unit-tests.xml'
    if junit.is_file():
        suite = ET.parse(junit).getroot().find('testsuite')
        if suite is not None:
            report['recorded_automated_tests'] = {key:int(suite.get(key,'0')) for key in ('tests','failures','errors','skipped')}
            report['recorded_automated_tests']['note'] = 'Existing software test run; not a physical sensor measurement.'
    output = ROOT / 'docs/evidence/runtime.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8766')
    capture(parser.parse_args().url)
