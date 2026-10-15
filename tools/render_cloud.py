"""Offline QA projection of saved observed 3D points. NOT an app screenshot."""
from pathlib import Path
import sys
import json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import cv2
import numpy as np
from guideglass.storage import MapStore


def render(xyz,rgb,angle):
    center=np.median(xyz,axis=0)
    rotation,_=cv2.Rodrigues(np.array([-.15,angle,0.],np.float64))
    points=(xyz-center)@rotation.T
    span=np.percentile(points[:,:2],99,axis=0)-np.percentile(points[:,:2],1,axis=0)
    scale=min(850/max(span[0],.1),570/max(span[1],.1))
    xy=(points[:,:2]*scale+[480,350]).astype(int)
    canvas=np.full((700,960,3),(13,6,2),np.uint8)
    # Back-to-front painter for point sprites; no triangulation or invented surfaces.
    for i in np.argsort(points[:,2])[::-1]:
        x,y=xy[i]
        if 0<=x<960 and 0<=y<700:cv2.circle(canvas,(x,y),1,tuple(int(c) for c in rgb[i,::-1]),-1)
    cv2.putText(canvas,'ACTUAL RGB-D POINT MAP - offline QA projection',(20,30),cv2.FONT_HERSHEY_SIMPLEX,.6,(230,230,230),1)
    cv2.putText(canvas,f'{len(xyz):,} measured-depth points | not a browser screenshot',(20,670),cv2.FONT_HERSHEY_SIMPLEX,.55,(170,190,200),1)
    return canvas


if __name__=='__main__':
    report=json.loads((ROOT/'.data/reports/verification.json').read_text())
    model,_,_=MapStore(ROOT/'.data/maps').load(report['rgbd']['map_id'])
    xyz,rgb,_=model.arrays()
    for name,angle in [('front',0.),('rotated',.55)]:
        cv2.imwrite(str(ROOT/f'.data/reports/point-cloud-{name}.png'),render(xyz,rgb,angle))
