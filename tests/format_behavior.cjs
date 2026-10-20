const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const F = require('../app/static/format_logic.js');
const formats = [
  {format_id:'a',kind:'audio',size_bytes:10,size_source:'exact'},
  {format_id:'v',kind:'video',size_bytes:100,size_source:'exact',duration:100},
  {format_id:'m',kind:'muxed',size_bytes:150,size_source:'exact'},
  {format_id:'u',kind:'unknown',size_bytes:null,size_source:'unknown'},
  {format_id:'e',kind:'audio',size_bytes:20,size_source:'bitrate_estimate',bitrate:128},
  {format_id:'n',kind:'audio',size_bytes:null,size_source:'unknown'},
  {format_id:'nv',kind:'video',size_bytes:null,size_source:'unknown'},
];
let s=F.choose(F.empty(),formats[0]);
assert.equal(s.audio,'a');assert.equal(s.video,'');
s=F.choose(s,formats[1]);assert.equal(F.expression(s),'v+a');
assert.deepEqual(F.restore('a',formats),{video:'',audio:'a',muxed:'',expert:''});
s=F.choose(s,formats[2]);assert.equal(F.expression(s),'m');assert.equal(s.audio,'');assert.equal(s.video,'');
assert.equal(F.expression(F.choose(s,formats[0])),'m');
assert.equal(F.expression(F.choose(s,formats[0],undefined,true)),'a');
assert.equal(F.expression(F.choose(F.empty(),formats[3])), '');
assert.equal(F.choose(F.empty(),formats[3],'audio').audio,'u');
for(const expr of ['bestvideo+bestaudio/best','v+a+e','v[height<=720]','m+a','u','missing'])assert.equal(F.restore(expr,formats).expert,expr);
assert.deepEqual(F.estimate(formats,'v+a'),{known:110,unknown:0,approximate:false,conversion:false});
assert.equal(F.estimate(formats,'v+e').approximate,true);
assert.deepEqual(F.estimate(formats,'v+n'),{known:100,unknown:1,approximate:false,conversion:false});
assert.match(F.describe(F.estimate(formats,'v+n'),String),/Известная часть.*неизвестен/);
assert.equal(F.describe(F.estimate(formats,'nv+n'),String),'Размер неизвестен');
assert.equal(F.estimate(formats,'m').known,150);
assert.equal(F.estimate(formats,'',{mode:'video'}).pending,true);
assert.equal(F.estimate(formats,'bestvideo+bestaudio/best').pending,true);
assert.equal(F.estimate(formats,'v',{section:10}).known,10);
assert.equal(F.estimate(formats,'a',{section:10}).known,null);
assert.equal(F.estimate(formats,'e',{section:10}).known,160000);
assert.match(F.describe(F.estimate(formats,'a',{conversion:true}),String),/после конвертации неизвестен/);
assert.match(F.describe(F.estimate(formats,'',{mode:'audio'}),String),/после аудиоконвертации неизвестен/);
// Run actual UI handlers with a small DOM stub: these tests execute app.js.
const elements = new Map();
const el=id=>{if(!elements.has(id))elements.set(id,{value:'',checked:false,disabled:false,dataset:{},classList:{add(){},remove(){},toggle(){}},addEventListener(){},querySelector(){return null}});return elements.get(id)};
let currentMode='manual',confirmAnswer=false;
const context={FormatLogic:F,console,Map,JSON,Number,String,Object,Boolean,Math,Promise,document:{getElementById:el,querySelector:selector=>selector==='[name=download_mode]:checked'?{value:currentMode}:selector.startsWith('[name=download_mode]')?{set checked(v){}}:null,querySelectorAll:()=>[],addEventListener(){}},setTimeout:()=>1,clearTimeout(){},confirm:()=>confirmAnswer,prompt:()=>null};
vm.createContext(context);
const script=fs.readFileSync(require.resolve('../app/static/app.js'),'utf8');
vm.runInContext(script.slice(0,script.lastIndexOf('(async()=>')),context);
vm.runInContext('setup()',context);
el('url').value='https://example.test';
context.formats=formats;
vm.runInContext('state.formats=formats;state.formatsKey=cacheKey();',context);
el('selected_format').value='a';
vm.runInContext('prepareFormats()',context);
assert.equal(el('pickedAudioFormat').textContent,'a');assert.equal(el('pickedVideoFormat').textContent,'—');
vm.runInContext('chooseFormat(formats[1])',context);assert.equal(el('formatFieldMirror').value,'v+a');
vm.runInContext('chooseFormat(formats[2]);chooseFormat(formats[0])',context);assert.equal(el('formatFieldMirror').value,'m');
confirmAnswer=true;vm.runInContext('chooseFormat(formats[0])',context);assert.equal(el('formatFieldMirror').value,'a');
vm.runInContext('chooseFormat(formats[3])',context);assert.equal(el('formatFieldMirror').value,'a');
el('formatFieldMirror').value='a';el('formatFieldMirror').oninput();el('useFormatBtn').onclick();assert.equal(el('selected_format').value,'a');
el('formatFieldMirror').value='bestvideo+bestaudio/best';el('formatFieldMirror').oninput();
assert.equal(el('pickedVideoFormat').textContent,'—');assert.equal(el('pickedAudioFormat').textContent,'—');
vm.runInContext('state.formatsKey="other request";estimate();renderFormats()',context);assert.match(el('estimatedSize').textContent,/после определения/);assert.equal(el('formatsBody').innerHTML,'');
console.log('format selection, size and UI behavioral checks passed');
assert.equal(F.estimate(formats,'v',{section:50,sectionStart:90}).known,10);
assert.equal(F.estimate(formats,'v',{section:50,sectionStart:110}).known,null);
// Mode changes remove hidden selections; access changes invalidate metadata.
let changeMode;
context.document.querySelectorAll=selector=>selector==='[name=download_mode]'?[{set onchange(fn){changeMode=fn}}]:[];
const inputHandlers=new Map();
for(const id of ['url','proxy_enabled','proxy','cookies_enabled','cookies_file','impersonate_enabled','impersonate_target','deno_enabled','extra_args'])el(id).addEventListener=(event,fn)=>inputHandlers.set(id,fn);
vm.runInContext('setup()',context);
el('selected_format').value='m';changeMode();assert.equal(el('selected_format').value,'');assert.equal(el('formatFieldMirror').value,'');
vm.runInContext('state.formats=formats;state.formatsKey=cacheKey()',context);
el('url').value='https://other.test';inputHandlers.get('url')();
assert.equal(vm.runInContext('currentFormats().length',context),0);
// Exercise structured API conflicts and ordinary-start continuation.
(async()=>{
  let responses=[{owner_job_id:'old',actions:['resume','rename'],message:'resume',code:'resume_available'}, {success:true}];
  const calls=[];
  context.fetch=async(path,options)=>{calls.push(path);const data=responses.shift();return {ok:!data.code,status:data.code?409:200,json:async()=>data.code?{detail:data}:data}};
  vm.runInContext("refreshLogs=async()=>{};resolveJobConflict=async()=> 'resume'",context);
  await vm.runInContext('performDownload()',context);
  assert.equal(calls[0],'/api/download');assert.equal(calls[1],'/api/download/retry?job_id=old');
  // A stale in-flight format result never replaces data for the changed URL.
  context.fetch=async()=>({ok:true,json:async()=>{el('url').value='changed again';return {success:true,formats}}});
  vm.runInContext('state.formats=[];state.formatsKey=""',context);
  await vm.runInContext('requestFormats(true)',context);
  assert.equal(vm.runInContext('state.formats.length',context),0);
  console.log('API conflict and stale-request behavioral checks passed');
})().catch(error=>{console.error(error);process.exitCode=1});
