import * as THREE from 'three';
import {OrbitControls} from '/vendor/OrbitControls.js';

const $ = id => document.getElementById(id);
const names = {person:'شخص',car:'سيارة',truck:'شاحنة',bus:'حافلة',motorcycle:'دراجة نارية',bicycle:'دراجة',chair:'كرسي',couch:'أريكة',tv:'شاشة',laptop:'حاسوب',book:'كتاب',bottle:'زجاجة',cup:'كوب',potted_plant:'نبات',dog:'كلب',cat:'قطة','dining table':'طاولة'};
const phases = {idle:'جاهز لبدء مسح',loading_models:'تحميل النماذج محليًا…',waiting_for_frame:'بانتظار صورة فعلية…',analyzing:'تحليل الصورة والعمق…',tracking:'دمج الإطارات المرصودة',tracking_lost:'فُقد التتبع — الدمج متوقف لهذا الإطار',completed:'اكتمل التسجيل',stopping:'إيقاف المعالجة…',stopped:'المسح متوقف',loaded:'خريطة محفوظة — عرض فقط',error:'توقفت المعالجة بسبب خطأ'};
const trackingNames = {waiting:'بانتظار الصور',initialized:'أصل الخريطة',tracking:'تتبع الكاميرا',relocalized:'استُعيد الموضع',lost:'التتبع مفقود',not_tracking_saved_map:'عرض محفوظ'};
let lastState = null, sequence = -1, fittedSession = null, activeStream = null, captureSession = null;
let starting = false, cameraTimer = null, frameInFlight = false, objectURLs = {}, latestImageTime = 0;
let faceBase = 'idle', faceOverride = null, recognition = null, listening = false;
let renderer, controls, pointsObject, trajectoryObject, cameraLines, scene, camera, animationID;
const labelContext = $('objectOverlay').getContext('2d');
const projected = new THREE.Vector3();

window.GuideGlassFace = {
  setState(state){faceOverride=state;paintFace(state);},
  restore(){faceOverride=null;paintFace(faceBase);}
};
function paintFace(state){$('aiFace').dataset.state=state;$('aiFace').setAttribute('aria-label',state);$('faceLabel').textContent=state[0].toUpperCase()+state.slice(1);}
function baseFace(state){faceBase=state;if(!faceOverride)paintFace(state);}

async function jsonRequest(path, data){
  const response=await fetch(path,data===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const value=await response.json();if(!response.ok)throw new Error(value.error||`HTTP ${response.status}`);return value;
}
function errorMessage(error){$('spatialStatus').textContent=error.message;baseFace('warning');}
function mapPoint(position){return new THREE.Vector3(position[0],-position[1],-position[2]);}
function createRenderer(){
  try{
    const canvas=$('cloudCanvas');
    renderer=new THREE.WebGLRenderer({canvas,antialias:false,alpha:false,powerPreference:'low-power'});
    renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.5));renderer.setClearColor(0x02060d);
    scene=new THREE.Scene();camera=new THREE.PerspectiveCamera(55,1,.02,250);camera.position.set(2,1,2);
    controls=new OrbitControls(camera,canvas);controls.enableDamping=true;controls.dampingFactor=.08;controls.target.set(0,0,-2);
    controls.maxDistance=100;controls.minDistance=.08;
    pointsObject=new THREE.Points(new THREE.BufferGeometry(),new THREE.PointsMaterial({size:.022,vertexColors:true,sizeAttenuation:true}));scene.add(pointsObject);
    trajectoryObject=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0x67e5c0}));scene.add(trajectoryObject);
    cameraLines=new THREE.LineSegments(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0xffcd81}));scene.add(cameraLines);
    new ResizeObserver(resize).observe($('cloudViewport'));resize();
    canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();$('spatialStatus').textContent='توقف WebGL. أعد تحميل الصفحة لاستعادة العرض؛ المعالجة محفوظة على Windows.';cancelAnimationFrame(animationID);});
    animate();
  }catch(error){$('cloudEmpty').textContent='WebGL 2 غير متاح في هذا المتصفح. يمكن حفظ الخريطة وتصدير PLY.';renderer=null;}
}
function resize(){
  if(!renderer)return;const box=$('cloudViewport').getBoundingClientRect();
  renderer.setSize(box.width,box.height,false);camera.aspect=box.width/box.height;camera.updateProjectionMatrix();
  $('objectOverlay').width=Math.round(box.width);$('objectOverlay').height=Math.round(box.height);
}
function animate(){
  animationID=requestAnimationFrame(animate);if(document.hidden||!renderer)return;
  controls.update();renderer.render(scene,camera);drawLabels();
}
function drawLabels(){
  const canvas=$('objectOverlay');labelContext.clearRect(0,0,canvas.width,canvas.height);
  labelContext.font='12px system-ui';labelContext.textAlign='center';
  for(const object of lastState?.detections||[]){
    if(!object.world_position)continue;
    projected.copy(mapPoint(object.world_position)).project(camera);
    if(projected.z < -1 || projected.z > 1 || Math.abs(projected.x)>1 || Math.abs(projected.y)>1)continue;
    const x=(projected.x+1)*canvas.width/2,y=(1-projected.y)*canvas.height/2;
    const title=(names[object.label]||object.label)+' · '+Math.round(object.confidence*100)+'%';
    const width=labelContext.measureText(title).width+16;
    labelContext.fillStyle='#071b2de6';labelContext.fillRect(x-width/2,y-26,width,23);
    labelContext.fillStyle='#b4e0ff';labelContext.fillText(title,x,y-10);
    labelContext.strokeStyle='#7cc9ff';labelContext.beginPath();labelContext.arc(x,y,4,0,Math.PI*2);labelContext.stroke();
  }
}
function fit(){
  if(!renderer||!pointsObject.geometry.attributes.position?.count)return;
  pointsObject.geometry.computeBoundingBox();const box=pointsObject.geometry.boundingBox;
  const center=box.getCenter(new THREE.Vector3()),radius=Math.max(.3,box.getSize(new THREE.Vector3()).length()/2);
  controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(radius*.45,radius*.25,radius*1.6));
  camera.near=Math.max(.01,radius/300);camera.far=Math.max(50,radius*20);camera.updateProjectionMatrix();controls.update();
}
function replacePositions(object, positions){
  const old=object.geometry;object.geometry=new THREE.BufferGeometry();object.geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));old.dispose();
}
function updatePose(state){
  if(!renderer)return;
  replacePositions(trajectoryObject,(state.trajectory||[]).flatMap(p=>[p[0],-p[1],-p[2]]));
  const pose=state.pose;
  if(!pose){replacePositions(cameraLines,[]);return;}
  const origin=[0,0,0],corners=[[-.06,-.045,.09],[.06,-.045,.09],[.06,.045,.09],[-.06,.045,.09]];
  function world(p){const out=pose.slice(0,3).map(row=>row[0]*p[0]+row[1]*p[1]+row[2]*p[2]+row[3]);return[out[0],-out[1],-out[2]];}
  const lines=[];for(let i=0;i<4;i++)lines.push(...world(origin),...world(corners[i]),...world(corners[i]),...world(corners[(i+1)%4]));
  replacePositions(cameraLines,lines);
}
async function updateCloud(state){
  if(sequence===state.cloud_sequence)return;
  const response=await fetch('/api/spatial/cloud?since='+sequence,{cache:'no-store'});
  if(response.status===304)return;if(!response.ok)throw new Error('تعذر جلب سحابة النقاط');
  const buffer=await response.arrayBuffer();if(buffer.byteLength<16)throw new Error('بيانات نقاط غير مكتملة');
  const header=new DataView(buffer),count=header.getUint32(4,true),seq=header.getUint32(8,true),stride=header.getUint32(12,true);
  if(new TextDecoder().decode(new Uint8Array(buffer,0,4))!=='GGP1'||count>80000||stride!==24||buffer.byteLength!==16+count*24)throw new Error('تنسيق سحابة النقاط غير صالح');
  const raw=new Float32Array(buffer,16),positions=new Float32Array(count*3),colors=new Float32Array(count*3);
  for(let i=0;i<count;i++){
    positions[3*i]=raw[6*i];positions[3*i+1]=-raw[6*i+1];positions[3*i+2]=-raw[6*i+2];
    for(let j=0;j<3;j++){const v=raw[6*i+3+j];colors[3*i+j]=v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4);}
  }
  if(renderer){replacePositions(pointsObject,positions);pointsObject.geometry.setAttribute('color',new THREE.BufferAttribute(colors,3));
    $('cloudEmpty').hidden=count>0;$('cloudEmpty').style.display=count?'none':'grid';
    if(count&&fittedSession!==state.session_id){fittedSession=state.session_id;fit();}}
  sequence=seq;
}
async function updateImage(id,path){
  const response=await fetch(path,{cache:'no-store'});if(!response.ok)return;
  const url=URL.createObjectURL(await response.blob()),previous=objectURLs[id];objectURLs[id]=url;
  $(id).src=url;$(id).hidden=false;if(previous)URL.revokeObjectURL(previous);
}
function showState(state){
  lastState=state;
  $('spatialStatus').textContent=state.error||phases[state.phase]||state.phase;
  $('pointCount').textContent=state.point_count.toLocaleString('ar');$('fusedCount').textContent=state.frames_fused;
  $('trackingState').textContent=trackingNames[state.tracking?.state]||state.tracking?.state||'';
  $('startScan').disabled=state.running||starting;$('stopScan').disabled=!state.running;
  $('openMap').disabled=state.running;$('saveMap').disabled=!state.point_count;
  const estimated=state.depth_kind==='model_estimated_metric';
  $('scaleStatus').textContent=state.depth_kind?(estimated?'عمق AI تقديري للمشاهد الداخلية؛ المسافات ليست قياس حساس أو LiDAR.':'عمق مسجّل من حساس Kinect؛ دقة الخريطة تتأثر بالمعايرة والتتبع.')+(state.intrinsics&&!state.intrinsics.calibrated?' معاملات العدسة غير معايرة لهذا الجهاز.':''):'لا توجد بيانات عمق بعد.';
  const t=state.tracking||{};
  $('trackingDetails').textContent=`إطارات مقبولة: ${state.frames_fused} · مرفوضة: ${state.frames_rejected} · نقاط تطابق مقبولة: ${t.inliers??'—'} · خطأ إسقاط وسيط: ${t.reprojection_median_px??'—'} px. ${t.confidence!=null?'مؤشر جودة هندسي: '+Math.round(t.confidence*100)+'% (ليس احتمال صحة الخريطة).':''}`;
  $('performanceDetails').textContent=`المعالجة الفعلية: ${state.processing_fps??'—'} إطار/ث · ${state.latency_ms??'—'} ms. الجهاز: ${state.models.device}. ${state.capacity_reached?'وصلت الخريطة إلى حد النقاط؛ احفظ وابدأ مسحًا جديدًا.':''}`;
  $('objectList').replaceChildren();
  if(!state.detector_enabled)$('objectList').textContent='كشف الأجسام غير مفعّل لهذه الجلسة.';
  else if(!state.detections?.length)$('objectList').textContent='لا توجد أجسام تتجاوز حد الثقة في آخر صورة.';
  for(const item of state.detections||[]){const chip=document.createElement('span');chip.className='object-item';chip.textContent=(names[item.label]||item.label)+' '+Math.round(item.confidence*100)+'%'+(item.depth?' · '+item.depth.toFixed(2)+(estimated?' م تقديري':' م من العمق'):' · موقع ثلاثي الأبعاد غير موثوق');$('objectList').append(chip);}
  if(state.detections?.length){const note=document.createElement('small');note.textContent='لا يوجد تحليل موثوق لحركة الأجسام في هذه النسخة؛ لا تصنيف «خطر متحرك».';$('objectList').append(note);}
  baseFace(state.error||t.state==='lost'?'warning':state.running?'analyzing':'idle');updatePose(state);
}
async function poll(){
  try{
    if(!document.hidden){const state=await jsonRequest('/api/spatial/state');showState(state);await updateCloud(state);
      if(state.last_frame_at&&state.last_frame_at!==latestImageTime){latestImageTime=state.last_frame_at;await Promise.all([updateImage('processedFrame','/api/spatial/frame'),updateImage('processedDepth','/api/spatial/depth')]);}
      if(activeStream&&!state.running)releaseCamera();}
  }catch(error){errorMessage(error);}
  setTimeout(poll,900);
}
function releaseCamera(){
  if(cameraTimer)clearTimeout(cameraTimer);cameraTimer=null;
  if(activeStream)activeStream.getTracks().forEach(track=>track.stop());activeStream=null;captureSession=null;$('localCamera').srcObject=null;
}
async function sendCameraFrame(){
  if(!activeStream||!captureSession||document.hidden)return;
  const video=$('localCamera');
  try{
    if(video.videoWidth&&!frameInFlight){frameInFlight=true;const ratio=Math.min(1,640/Math.max(video.videoWidth,video.videoHeight));
      const canvas=document.createElement('canvas');canvas.width=Math.round(video.videoWidth*ratio);canvas.height=Math.round(video.videoHeight*ratio);
      canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
      const timestamp=performance.timeOrigin/1000+performance.now()/1000;
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.78));
      if(blob&&captureSession){const response=await fetch(`/api/spatial/frame?session=${captureSession}&timestamp=${timestamp}`,{method:'POST',headers:{'Content-Type':'image/jpeg'},body:blob});if(!response.ok){const data=await response.json();throw new Error(data.error);}}}
  }catch(error){errorMessage(error);releaseCamera();}
  finally{frameInFlight=false;if(activeStream)cameraTimer=setTimeout(sendCameraFrame,350);}
}
async function startScan(){
  if(starting||lastState?.running)return;starting=true;$('startScan').disabled=true;
  try{
    const source=$('scanSource').value,options={source,detect:$('enableDetection').checked,camera_index:Number($('cameraIndex').value),depth_size:Number($('depthSize').value)};
    const calibration=$('calibrationFile').files[0];if(calibration){if(calibration.size>20000)throw new Error('ملف المعايرة أكبر من الحد');options.intrinsics=JSON.parse(await calibration.text());}
    if(source==='video'){
      const file=$('scanVideo').files[0];if(!file)throw new Error('اختر ملف فيديو أولًا');if(file.size>120000000)throw new Error('الحد الأقصى للفيديو 120 MB');
      $('spatialStatus').textContent='نقل الفيديو إلى Windows داخل شبكتك…';
      const response=await fetch('/api/spatial/upload',{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:file});const result=await response.json();if(!response.ok)throw new Error(result.error);options.video_id=result.video_id;
    }
    if(source==='browser'){
      if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw new Error('كاميرا Safari تحتاج HTTPS موثوقًا. يمكن عرض تسجيل أو كاميرا Windows عبر هذا الرابط.');
      activeStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:640},height:{ideal:480}},audio:false});
      $('localCamera').srcObject=activeStream;await $('localCamera').play();
    }
    const state=await jsonRequest('/api/spatial/start',options);latestImageTime=0;showState(state);
    if(source==='browser'){captureSession=state.session_id;sendCameraFrame();}
  }catch(error){releaseCamera();errorMessage(error);}
  finally{starting=false;$('startScan').disabled=!!lastState?.running;}
}
async function stopScan(){releaseCamera();try{showState(await jsonRequest('/api/spatial/stop',{}));}catch(error){errorMessage(error);}}
async function refreshMaps(selected=''){
  const {maps}=await jsonRequest('/api/spatial/maps');$('savedMaps').replaceChildren(new Option('اختر خريطة محفوظة',''));
  for(const map of maps)$('savedMaps').add(new Option(`${map.name} · ${map.point_count.toLocaleString()} نقطة`,map.id));
  if(selected)$('savedMaps').value=selected;updateDownload();
}
function updateDownload(){const id=$('savedMaps').value;$('downloadPly').hidden=!id;if(id){$('downloadPly').href=`/api/spatial/maps/${id}.ply`;$('downloadPly').download=`GuideGlass-${id}.ply`;}}
$('scanSource').onchange=()=>{$('videoFileLabel').hidden=$('scanSource').value!=='video';$('cameraContext').textContent=$('scanSource').value==='browser'?'كاميرا الآيفون تحتاج HTTPS موثوقًا وإذن الكاميرا؛ تنقل الصور إلى Windows فقط.':'بدء مسح جديد يستبدل الخريطة غير المحفوظة فقط. التسجيلات تستمر حتى نهايتها أو الإيقاف.';};
$('startScan').onclick=startScan;$('stopScan').onclick=stopScan;$('fitCloud').onclick=fit;
$('saveMap').onclick=async()=>{try{const saved=await jsonRequest('/api/spatial/save',{name:$('mapName').value});$('mapStatus').textContent=`حُفظت ${saved.point_count.toLocaleString()} نقطة على Windows.`;await refreshMaps(saved.id);}catch(error){$('mapStatus').textContent=error.message;}};
$('openMap').onclick=async()=>{try{const id=$('savedMaps').value;if(!id)throw new Error('اختر خريطة محفوظة');showState(await jsonRequest('/api/spatial/load',{id}));$('mapStatus').textContent='فُتحت الخريطة المحفوظة. بدء مسح جديد ينشئ نظام إحداثيات جديدًا.';}catch(error){$('mapStatus').textContent=error.message;}};
$('savedMaps').onchange=updateDownload;
const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
if(!Recognition){$('listenCommand').disabled=true;$('listeningSupport').textContent='التعرف الصوتي غير متاح بهذا المتصفح. النطق وأزرار التحكم يعملان؛ التنبيه المهم بالعربية.';}
else{
  recognition=new Recognition();recognition.continuous=false;recognition.interimResults=false;
  recognition.onstart=()=>{listening=true;window.GuideGlassFace.setState('listening');$('listenCommand').textContent='جارٍ الاستماع…';};
  recognition.onend=()=>{listening=false;window.GuideGlassFace.restore();$('listenCommand').textContent='أمر صوتي: ابدأ / توقف';};
  recognition.onerror=event=>{$('listeningSupport').textContent='تعذر الاستماع: '+event.error;};
  recognition.onresult=event=>{const text=event.results[0][0].transcript.trim();$('listeningSupport').textContent='سمعت: '+text;if(/توقف|أوقف|وقف|stop/i.test(text))stopScan();else if(/ابدأ|إبدأ|start/i.test(text))startScan();};
  $('listenCommand').onclick=()=>{if(listening)recognition.stop();else{recognition.lang=$('voiceLanguage').value;recognition.start();}};
}
document.addEventListener('visibilitychange',()=>{if(document.hidden&&activeStream)stopScan();});
window.addEventListener('pagehide',()=>{releaseCamera();for(const url of Object.values(objectURLs))URL.revokeObjectURL(url);});
createRenderer();refreshMaps().catch(errorMessage);poll();
