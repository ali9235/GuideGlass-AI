"""Non-billable integration: actual HTTP + real recorded video + real CPU AI."""
import http.client
import json
from pathlib import Path
import sys
import threading
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import cv2
import numpy as np
from server import GuideGlassServer
from guideglass.sources import RecordingSource


def run():
    server=GuideGlassServer(('127.0.0.1',0))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def request(path,body=None,mime='application/json'):
        connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=30)
        if body is not None and not isinstance(body,bytes):body=json.dumps(body).encode()
        connection.request('POST' if body is not None else 'GET',path,body,{'Content-Type':mime})
        response=connection.getresponse();raw=response.read();connection.close()
        if response.status>=400:raise RuntimeError(f'{path}: HTTP {response.status}: {raw[:400]!r}')
        return json.loads(raw) if response.getheader('Content-Type','').startswith('application/json') else raw
    def wait_finished(deadline=90):
        end=time.monotonic()+deadline
        states=[]
        while time.monotonic()<end:
            state=request('/api/spatial/state');states.append((state['phase'],state['point_count']))
            if not state['running']:
                if state['error']:raise RuntimeError(state['error'])
                return state,states
            time.sleep(.3)
        raise RuntimeError('Real integration scan exceeded time limit')
    report={}
    try:
        assert request('/api/status')['ai']
        assert b'cloudCanvas' in request('/')
        assert b'WebGLRenderer' in request('/static/spatial.js')
        assert b'WebGLRenderer' in request('/vendor/three.module.js')
        request('/api/spatial/start',dict(source='sample',detect=False))
        state,states=wait_finished()
        assert state['frames_fused']>100 and state['point_count']>10000
        assert len({points for _,points in states})>2,'Cloud did not update during scan'
        saved=request('/api/spatial/save',dict(name='HTTP real RGB-D test'))
        before=server.spatial.map.arrays()
        request('/api/spatial/load',dict(id=saved['id']))
        for a,b in zip(before,server.spatial.map.arrays()):np.testing.assert_array_equal(a,b)
        assert request(f"/api/spatial/maps/{saved['id']}.ply").startswith(b'ply')
        report['rgbd_http']={'frames_fused':state['frames_fused'],'points':state['point_count'],
            'distinct_live_point_counts_observed':len({points for _,points in states}),'save_load_exact':True}
        # Real RGB-only MP4. No depth tensor is supplied to the video pipeline.
        source=RecordingSource(ROOT/'.data/samples/tum_xyz')
        path=ROOT/'.data/reports/http-source.mp4'
        writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),10,(640,480))
        for _ in range(5):
            rgb,_,_,_=source.read();writer.write(cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
        writer.release()
        upload=request('/api/spatial/upload',path.read_bytes(),'video/mp4')
        request('/api/spatial/start',dict(source='video',video_id=upload['video_id'],detect=True,
            intrinsics=source.intrinsics.json()))
        state,states=wait_finished()
        assert state['depth_kind']=='model_estimated_metric' and state['frames_fused']>=3 and state['point_count']>0
        assert request('/api/spatial/frame').startswith(b'\xff\xd8')
        assert request('/api/spatial/depth').startswith(b'\xff\xd8')
        report['rgb_video_http']={'frames_processed':state['frames_processed'],'frames_fused':state['frames_fused'],
            'points':state['point_count'],'depth_kind':state['depth_kind'],'actual_upload_bytes':upload['bytes'],
            'detector_enabled':state['detector_enabled'],'last_detections':state['detections']}
        request('/api/spatial/start',dict(source='sample',detect=False))
        request('/api/spatial/stop',{})
        state,_=wait_finished()
        assert state['phase']=='stopped'
        report['stop_verified']=True
        report['live_hardware_tested']=False
        report['browser_render_tested']=False
        (ROOT/'.data/reports/http-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))
    finally:
        server.spatial.stop()
        if server.spatial.worker:server.spatial.worker.join(timeout=15)
        server.shutdown();server.server_close();thread.join(timeout=3)


if __name__=='__main__':run()
