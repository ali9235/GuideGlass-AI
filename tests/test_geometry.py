import cv2
import numpy as np
import pytest
from guideglass.geometry import Intrinsics, backproject, transform_points, VoxelMap, PoseTracker, detection_locations
from guideglass.models import static_mask


def test_backproject_metric_equations(unit_rgbd):
    rgb, d, k = unit_rgbd
    points, colors = backproject(d, rgb, k, stride=1)
    np.testing.assert_allclose(points[0], [-159.5*2/250, -119.5*2/250, 2], rtol=1e-6)
    np.testing.assert_array_equal(colors[0], rgb[0,0])
    assert len(points) == d.size


@pytest.mark.parametrize("bad", [0, -1, np.nan, np.inf, 13])
def test_no_points_for_unobserved_or_out_of_range(unit_rgbd, bad):
    rgb, d, k = unit_rgbd
    d[:] = bad
    assert len(backproject(d, rgb, k)[0]) == 0


def test_shape_mismatch_rejected(unit_rgbd):
    rgb, d, k = unit_rgbd
    with pytest.raises(ValueError): backproject(d[:-1],rgb,k)


def test_resize_pixel_centers():
    k = Intrinsics(640,480,525,525,319.5,239.5).resized(320,240)
    assert (k.fx,k.fy,k.cx,k.cy)==(262.5,262.5,159.5,119.5)


def test_unrectified_input_rejected():
    with pytest.raises(ValueError): Intrinsics.from_dict(dict(width=640,height=480,fx=525,fy=525,cx=320,cy=240,distortion=[.1]))


@pytest.mark.parametrize('change',[{'width':640.5},{'fx':float('nan')},{'calibrated':'false'},{'source':None}])
def test_invalid_calibration_rejected(change):
    data=dict(width=640,height=480,fx=525,fy=525,cx=320,cy=240);data.update(change)
    with pytest.raises(ValueError):Intrinsics.from_dict(data)


def test_transform_direction():
    p=np.eye(4);p[:3,3]=[1,2,3]
    np.testing.assert_allclose(transform_points(np.array([[0,0,2]]),p),[[1,2,5]])


def test_voxel_mean_limit_and_missing_points():
    m=VoxelMap(.01,100)
    xyz=np.column_stack((np.arange(200)*.02,np.zeros(200),np.ones(200))).astype(np.float32)
    colors=np.full((200,3),100,np.uint8)
    m.fuse(xyz,colors);m.fuse(xyz,colors)
    assert len(m.cells)==100 and m.capacity_reached
    p,c,n=m.arrays()
    assert np.all(c==100) and np.all(n==2) and len(m.arrays(20)[0])==20


def test_pnp_pose_and_lost_frame(unit_rgbd):
    rgb,d,k=unit_rgbd;t=PoseTracker();mask=np.ones(d.shape,bool)
    first,_=t.update(rgb,d,k,mask,1)
    np.testing.assert_allclose(first,np.eye(4))
    shifted=cv2.warpAffine(rgb,np.float32([[1,0,4],[0,1,0]]),(320,240))
    pose,metrics=t.update(shifted,d,k,mask,2)
    assert pose is not None,metrics
    np.testing.assert_allclose(pose[:3,3],[-4*2/250,0,0],atol=.012)
    reference=t.reference
    lost,metrics=t.update(np.zeros_like(rgb),d,k,mask,3)
    assert lost is None and metrics["state"]=="lost" and t.reference is reference


def test_static_mask_and_no_moving_hazard(unit_rgbd):
    _,d,k=unit_rgbd
    detections=[dict(label="person",box=[40,40,120,160],confidence=.9,potentially_dynamic_class=True)]
    mask=static_mask(d.shape,detections)
    assert not mask[100,80] and mask[10,10]
    result=detection_locations(detections,d,k,np.eye(4),"model_estimated_metric")[0]
    assert result["world_position"] is not None
    assert result["depth_kind"]=="model_estimated_metric" and not result["moving_hazard"]
    assert result["motion"]=="unassessed"
    assert detection_locations(detections,d,k,None,"sensor_metric")[0]["world_position"] is None


def test_bad_depth_does_not_locate_object(unit_rgbd):
    _,d,k=unit_rgbd;d[:]=0
    result=detection_locations([dict(label="car",box=[40,40,120,160])],d,k,np.eye(4),"sensor_metric")[0]
    assert result["world_position"] is None
