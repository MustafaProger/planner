const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/refresh.js','utf8');
const nextTick=()=>new Promise(resolve=>setImmediate(resolve));

async function setup(initial={status:'idle',last_finished_at:null},options={}){
 let response=initial,focus=false,dialog=false,dataHook=null,renders=0,dataReads=0;
 const listeners={},posts=[];let mounted=false;
 const button={},details={open:false},summary={focus(){}};
 const bar={dataset:{},innerHTML:'',setAttribute(){},contains:()=>false,querySelector:selector=>selector==='details'?details:selector==='button'?button:selector==='summary'?summary:{}};
 const header={insertAdjacentElement(){mounted=true}};
 const document={hidden:false,activeElement:{matches:()=>focus},
  querySelector:selector=>selector==='dialog[open]'&&dialog?{}:selector==='#main > header'&&options.header?header:selector==='.refresh-trigger'&&mounted?button:null,
  querySelectorAll:()=>[],getElementById:id=>id==='data-refresh'&&mounted?bar:null,createElement:()=>bar,
  addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn)};
 const context=vm.createContext({document,location:{pathname:'/analytics/statistics'},
  window:{},MutationObserver:class{observe(){}},setInterval(){},setTimeout,
  U:{role:'admin'},D:{version:'initial'},tab:'statistics',from:'2026-08-01',to:'2026-08-31',
  esc:String,toast(){},enhanceTables(){},boot:async()=>{},
  render:async()=>{renders++},
  api:async(path,options={})=>{
   if(path==='refresh'&&options.method==='POST'){posts.push(JSON.parse(options.body));return {accepted:true,status:'running'}}
   if(path==='refresh')return response;
   assert.equal(path,'data');dataReads++;
   if(dataHook)await dataHook();
   return {version:'fresh'};
  }});
 vm.runInContext(source,context);
 await nextTick();
 return {context,posts,bar,manual:()=>button.onclick(),response:value=>response=value,focus:value=>focus=value,dialog:value=>dialog=value,
  dataHook:value=>dataHook=value,stats:()=>({renders,dataReads}),poll:()=>context.window.fleetRefresh.poll(),
  update:()=>context.window.fleetRefresh.updateView(),dispatch:(name,target)=>{
   for(const listener of listeners[name]||[])listener({target});
  }};
}

test('first completion after a null baseline refreshes data immediately',async()=>{
 const env=await setup();
 assert.deepEqual(env.stats(),{renders:0,dataReads:0});
 env.response({status:'running',last_finished_at:null});await env.poll();
 env.response({status:'success',last_finished_at:'2026-10-29T12:00:00+03:00'});await env.poll();
 assert.deepEqual(env.stats(),{renders:1,dataReads:1});
 assert.equal(env.context.D.version,'fresh');
 await env.poll();assert.deepEqual(env.stats(),{renders:1,dataReads:1});
});

test('initial completed baseline does not duplicate startup rendering; next completion does',async()=>{
 const env=await setup({status:'success',last_finished_at:'2026-10-29T12:00:00+03:00'});
 assert.deepEqual(env.stats(),{renders:0,dataReads:0});
 env.response({status:'success',last_finished_at:'2026-10-29T12:05:00+03:00'});await env.poll();
 assert.deepEqual(env.stats(),{renders:1,dataReads:1});
});

test('first completion is deferred while an input has focus or a dialog is open',async()=>{
 const env=await setup();env.focus(true);
 env.response({status:'success',last_finished_at:'2026-10-29T12:00:00+03:00'});await env.poll();
 assert.deepEqual(env.stats(),{renders:0,dataReads:0});assert.equal(env.context.D.version,'initial');
 env.focus(false);env.dialog(true);await env.update();
 assert.deepEqual(env.stats(),{renders:0,dataReads:0});
 env.dialog(false);await env.update();
 assert.deepEqual(env.stats(),{renders:1,dataReads:1});
});

test('unsaved forms and failed submissions keep data state and input intact',async()=>{
 const env=await setup();const form={isConnected:true,closest:()=>null};
 const input={type:'text',closest:()=>form};env.dispatch('input',input);
 env.response({status:'success',last_finished_at:'2026-10-29T12:00:00+03:00'});await env.poll();
 assert.deepEqual(env.stats(),{renders:0,dataReads:0});
 env.dispatch('submit',form);await env.update(); // Saving may fail: still connected and dirty.
 assert.deepEqual(env.stats(),{renders:0,dataReads:0});assert.equal(env.context.D.version,'initial');
 form.isConnected=false;await env.update();
 assert.deepEqual(env.stats(),{renders:1,dataReads:1});
});

test('typing that starts during data fetch does not replace the current dataset or form',async()=>{
 const env=await setup();env.dataHook(async()=>env.focus(true));
 env.response({status:'success',last_finished_at:'2026-10-29T12:00:00+03:00'});await env.poll();
 assert.deepEqual(env.stats(),{renders:0,dataReads:1});assert.equal(env.context.D.version,'initial');
 env.focus(false);env.dataHook(null);await env.update();
 assert.deepEqual(env.stats(),{renders:1,dataReads:2});assert.equal(env.context.D.version,'fresh');
});

for(const provider of ['neftm','rosneft'])test(`global button uses the selected historical ${provider} data period`,async()=>{
 const env=await setup(undefined,{header:true});
 env.context.tab=provider+'data';
 env.context.fuelPeriods={neftm:{from:'2026-08-01',to:'2026-08-31'},rosneft:{from:'2026-09-01',to:'2026-09-30'}};
 await env.poll();
 const period=env.context.fuelPeriods[provider];
 assert.ok(env.bar.innerHTML.includes(`Кнопка: ${period.from} — ${period.to}`));
 await env.manual();
 assert.deepEqual(env.posts,[period]);
});

test('inactive server scheduler is reported honestly',async()=>{
 const env=await setup({status:'idle',last_finished_at:null,server_scheduler:false},{header:true});
 assert.ok(env.bar.innerHTML.includes('Автообновление сервера не запущено'));
 assert.ok(!env.bar.innerHTML.includes('Автообновление каждые 5 минут'));
});
