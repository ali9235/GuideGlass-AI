"""Run the actual local detector on OpenCV's public real-photo test fixture."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import cv2
from guideglass.models import LocalModels
from guideglass.sources import decode_image
from prepare_assets import download


if __name__=='__main__':
    url='https://raw.githubusercontent.com/opencv/opencv_extra/4.x/testdata/dnn/dog416.png'
    path=download(url,ROOT/'.data/downloads/opencv-dog416.png',2000000)
    rgb=decode_image(path.read_bytes());models=LocalModels(ROOT/'models');models.load(False,True)
    detections=models.detect(rgb)
    report={'source_url':url,'input_kind':'real_photo_public_OpenCV_test_fixture',
        'detections':detections,'vehicle_detected':any(d['label'] in {'car','truck','bus'} for d in detections),
        'depth_available':False,'motion_assessed':False,'inference':'actual_local_SSDLite_COCO'}
    (ROOT/'.data/reports/object-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    annotated=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
    for d in detections:
        x1,y1,x2,y2=map(int,d['box'])
        cv2.rectangle(annotated,(x1,y1),(x2,y2),(255,200,100),1)
        cv2.putText(annotated,f"{d['label']} {d['confidence']:.2f}",(x1,max(15,y1-5)),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,200,100),1)
    cv2.imwrite(str(ROOT/'.data/reports/object-detections.jpg'),annotated)
    print(json.dumps(report,indent=2))
