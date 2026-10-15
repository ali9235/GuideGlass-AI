import http.client
import json
import threading
from pathlib import Path
import pytest
from server import GuideGlassServer, valid_private_device, NoRedirect


@pytest.fixture
def server(tmp_path):
    (tmp_path/'index.html').write_text('<title>Existing GuideGlass</title>',encoding='utf-8')
    s=GuideGlassServer(('127.0.0.1',0),root=tmp_path)
    t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
    yield s
    s.shutdown();s.server_close();t.join(2)


def request(server,path,method='GET',data=None,headers=None):
    c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
    body=json.dumps(data).encode() if data is not None else None
    all_headers={'Content-Type':'application/json'};all_headers.update(headers or {})
    c.request(method,path,body,all_headers);r=c.getresponse();result=(r.status,r.read());c.close();return result


def test_startup_and_original_bridge(server):
    assert request(server,'/')[0]==200
    status,raw=request(server,'/api/status');assert status==200 and json.loads(raw)['bridge']=='ready'
    assert request(server,'/api/frame')[0]==503
    assert request(server,'/api/distance')[0]==503
    assert request(server,'/api/device','POST',{'ip':'192.168.1.20'})[0]==200
    server.device_fetch=lambda *args:(b'{"distance_mm":750,"valid":true}','application/json')
    status,raw=request(server,'/api/distance');assert status==200 and json.loads(raw)['distance_mm']==750
    server.device_fetch=lambda *args:(b'image-bytes','image/jpeg')
    assert request(server,'/api/frame')==(200,b'image-bytes')


def test_spatial_contract_empty_is_empty(server):
    status,raw=request(server,'/api/spatial/state');state=json.loads(raw)
    assert status==200 and state['point_count']==0 and state['frames_fused']==0
    status,raw=request(server,'/api/spatial/cloud');assert status==200 and len(raw)==16
    assert request(server,f"/api/spatial/cloud?since={state['cloud_sequence']}")[0]==304
    assert request(server,'/api/spatial/frame')[0]==404
    assert request(server,'/api/spatial/save','POST',{})[0]==400
    assert request(server,'/api/spatial/start','POST',{'source':'sample'})[0]==400
    assert request(server,'/api/spatial/stop','POST',{})[0]==200


@pytest.mark.parametrize('path',['/.env','/server.py','/.git/config','/../server.py','/api/spatial/maps/../../secret.ply'])
def test_private_files_are_not_served(server,path):
    assert request(server,path)[0]==404


def test_host_origin_and_content_type(server):
    assert request(server,'/api/status',headers={'Host':'attacker.example'})[0]==403
    assert request(server,'/api/device','POST',{'ip':'192.168.1.2'}, {'Origin':'https://attacker.example'})[0]==403
    assert request(server,'/api/device','POST',{'ip':'192.168.1.2'}, {'Content-Type':'text/plain'})[0]==400
    assert request(server,'/api/device','POST',{'ip':'8.8.8.8'})[0]==400


@pytest.mark.parametrize('ip',['127.0.0.1','169.254.169.254','0.0.0.0','8.8.8.8','example.org','::1','192.168.1.999'])
def test_proxy_is_restricted_to_lan(ip):assert not valid_private_device(ip)


def test_device_redirects_rejected():
    with pytest.raises(ValueError):NoRedirect().redirect_request(None,None,302,'Found',{},'http://internet.example')
