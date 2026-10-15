// Logic/DOM-contract unit tests only. These are NOT a Safari/WebGL device test.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const html=fs.readFileSync('index.html','utf8'), spatial=fs.readFileSync('static/spatial.js','utf8');
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
assert.equal(new Set(ids).size,ids.length,'Duplicate DOM IDs');
for(const match of spatial.matchAll(/\$\('([^']+)'\)/g))assert.ok(ids.includes(match[1]),`Missing DOM ID: ${match[1]}`);
const elements=new Map(ids.map(id=>[id,{value:'',textContent:'',options:[],children:[],style:{},dataset:{},
  add(option){this.options.push(option);},replaceChildren(...options){this.options=options;},prepend(value){this.children.unshift(value);}}]));
elements.get('voiceLanguage').value='en-US';elements.get('voiceRate').value='0.9';
const spoken=[];
const context={console,Option:function(text,value){this.text=text;this.value=value;},
  document:{getElementById:id=>elements.get(id),querySelectorAll:()=>[],createElement:()=>({})},
  window:{speechSynthesis:{getVoices:()=>[],addEventListener(){},cancel(){},speak(u){spoken.push(u);}}},
  SpeechSynthesisUtterance:function(text){this.text=text;},setInterval(){},fetch:async()=>({ok:true,json:async()=>({})})};
context.speechSynthesis=context.window.speechSynthesis;
vm.createContext(context);
vm.runInContext(html.match(/<script>\s*([\s\S]*?)<\/script>/)[1],context);
for(const [input,expected] of [[{distance_mm:750},75],[{distance_cm:42},42],[750,75],
  [{valid:false,distance_mm:100},null],[{distance_mm:0},null],[{distance_mm:-2},null],
  [{status:'error',distance_mm:100},null],[{},null],[null,null],[{distance_mm:'nonsense'},null]]){
  context.input=input;assert.equal(vm.runInContext('parseCm(input)',context),expected);
}
assert.equal(vm.runInContext("speak('ordinary')",context),true);
const old=spoken.at(-1);assert.equal(old.lang,'en-US');
assert.equal(vm.runInContext("speak('important',true)",context),true);
const alert=spoken.at(-1);assert.equal(alert.lang,'ar-SA');
old.onend();assert.equal(vm.runInContext("speak('must not interrupt')",context),false);
alert.onend();assert.equal(vm.runInContext("speak('now permitted')",context),true);
assert.ok(spatial.includes('window.isSecureContext'));
assert.ok(spatial.includes('track.stop()'));
assert.ok(spatial.includes('motion')||html.includes('Visual Odometry'));
console.log('PASS: DOM IDs, 10 sensor formats, Arabic priority, late speech callback, capture safety contract. Not a browser/device test.');
