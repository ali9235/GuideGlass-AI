import json
import struct
import threading
import time
import cv2
import numpy as np
import pytest
from guideglass.engine import SpatialEngine
from guideglass.geometry import VoxelMap
from guideglass.storage import MapStore
from guideglass.sources import decode_image, bounded_rgb


def test_loss_duplicate_stop_and_binary(tmp_path,unit_rgbd,stub_models):
    rgb,d,k=unit_rgbd;e=SpatialEngine(tmp_path,models=stub_models)
    e.process_frame(rgb,d,k,1,False);points=len(e.map.cells);seq=e.sequence
    assert points>0
    raw=e.cloud();magic,n,version,stride=struct.unpack('<4sIII',raw[:16])
    assert (magic,n,version,stride)==(b'GGP1',points,seq,24) and len(raw)==16+points*24
    assert e.cloud(seq) is None
    e.process_frame(rgb,d,k,1,False)
    assert e.info['frames_dropped']==1 and e.sequence==seq
    e.process_frame(np.zeros_like(rgb),d,k,2,False)
    assert e.info['frames_rejected']==1 and e.sequence==seq and len(e.map.cells)==points
    e.stop();e.process_frame(rgb,d,k,3,False)
    assert e.sequence==seq


def test_stop_during_inference_prevents_fusion(tmp_path,unit_rgbd,stub_models):
    rgb,d,k=unit_rgbd;e=SpatialEngine(tmp_path,models=stub_models)
    def depth(_): e.stop();return d
    stub_models.depth=depth
    e.process_frame(rgb,None,k,1,False)
    assert not e.map.cells and e.info['frames_fused']==0


def test_save_reopen_cloud_exact(tmp_path,unit_rgbd,stub_models):
    rgb,d,k=unit_rgbd;e=SpatialEngine(tmp_path,models=stub_models)
    e.process_frame(rgb,d,k,1,False)
    saved=e.save_map('real persistence unit test');before=e.map.arrays()
    e.load_map(saved['id']);after=e.map.arrays()
    for a,b in zip(before,after): np.testing.assert_array_equal(a,b)
    assert e.state()['map_mode']=='view_only' and e.maps.list()[0]['id']==saved['id']
    assert e.maps.ply(saved['id']).startswith(b'ply\nformat binary_little_endian')


def test_float32_centroid_boundary_regression(tmp_path):
    # Float32(0.035 - epsilon) lands on 0.035; voxel identity must survive.
    m=VoxelMap(.035)
    m.cells[(0,0,28)]=(np.array([.035-1e-10,.01,1.,10,20,30]),2)
    m.cells[(1,0,28)]=(np.array([.035+1e-10,.01,1.,40,50,60]),3)
    s=MapStore(tmp_path);saved=s.save(m,[],dict(source='unit',depth_kind='unit',intrinsics=None))
    reopened,_,_=s.load(saved['id'])
    assert len(reopened.cells)==2 and list(reopened.cells)==list(m.cells)
    for a,b in zip(m.arrays(),reopened.arrays()): np.testing.assert_array_equal(a,b)


@pytest.mark.parametrize('map_id',['../secret','',None,'a'*31,'z'*32])
def test_map_path_rejected(tmp_path,map_id):
    with pytest.raises(ValueError): MapStore(tmp_path).load(map_id)


def test_empty_map_cannot_save(tmp_path):
    with pytest.raises(ValueError): MapStore(tmp_path).save(VoxelMap(),[],{})


def test_missing_model_and_invalid_source_are_errors(tmp_path,stub_models):
    e=SpatialEngine(tmp_path,models=stub_models)
    with pytest.raises(ValueError):e.start(dict(source='pretend'))
    with pytest.raises(ValueError):e.start(dict(source='sample'))
    with pytest.raises(ValueError):e.start(dict(source='video',video_id='../secret'))


def test_browser_frame_ingestion_and_concurrent_start(tmp_path,unit_rgbd,stub_models):
    rgb,_,_=unit_rgbd;e=SpatialEngine(tmp_path,models=stub_models)
    state=e.start(dict(source='browser',detect=False))
    raw=cv2.imencode('.jpg',cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))[1].tobytes()
    try:
        with pytest.raises(ValueError):e.start(dict(source='browser'))
        with pytest.raises(ValueError):e.submit_frame(raw,'old-session',1)
        e.submit_frame(raw,state['session_id'],1)
        deadline=time.monotonic()+4
        while not e.info['frames_processed'] and time.monotonic()<deadline:time.sleep(.02)
        assert e.info['frames_fused']==1
    finally:e.stop();e.worker.join(timeout=5)
    assert e.info['phase']=='stopped' and not e.worker.is_alive()
    with pytest.raises(ValueError):e.submit_frame(raw,state['session_id'],2)


def test_decode_and_bound_actual_encoded_image(unit_rgbd):
    rgb,_,_=unit_rgbd
    raw=cv2.imencode('.png',cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))[1].tobytes()
    np.testing.assert_array_equal(decode_image(raw),rgb)
    assert bounded_rgb(np.zeros((900,1200,3),np.uint8)).shape==(480,640,3)
    with pytest.raises(ValueError):decode_image(b'')


def test_bad_archive_metadata_rejected(tmp_path):
    s=MapStore(tmp_path);identifier='a'*32
    np.savez(s.path(identifier),metadata=np.frombuffer(b'{"schema":99}',np.uint8))
    with pytest.raises(ValueError):s.load(identifier)


def test_truncated_map_rejected_cleanly(tmp_path):
    s=MapStore(tmp_path);identifier='b'*32
    s.path(identifier).write_bytes(b'not a map')
    with pytest.raises(ValueError,match='corrupt'):s.load(identifier)
