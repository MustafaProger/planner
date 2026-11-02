const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/refresh.js','utf8');
const nextTick=()=>new Promise(resolve=>setImmediate(resolve));

async function setup(initial={status:'idle',last_finished_at:null},options={}){
 let response=initial,focus=false,dialog=false,dataHook=null,renders=0,dataReads=0;
 const listeners={},posts=[];let mounted=false;
 const button={},summary={textContent:'Период и состояние обновления',focus(){}},details={open:false,dataset:{},querySelector:()=>summary};
 const nodes={'button':button,'details':details,'summary':summary,'.refresh-status':{},'.refresh-checked':{},'.refresh-details-body':{innerHTML:''},'.refresh-alerts':{innerHTML:''}};
 let replacements=0,markup='';
 const bar={dataset:{},get innerHTML(){return markup},set innerHTML(value){markup=value;replacements++},setAttribute(){},contains:()=>false,querySelector:selector=>nodes[selector]};
 const header={insertAdjacentElement(){mounted=true}};
 const document={hidden:false,activeElement:{matches:()=>focus},
  querySelector:selector=>selector==='dialog[open]'&&dialog?{}:selector==='#main > header'&&options.header?header:selector==='.refresh-trigger'&&mounted?button:null,
  querySelectorAll:selector=>selector==='#main details'&&mounted?[details]:[],getElementById:id=>id==='data-refresh'&&mounted?bar:null,createElement:()=>bar,
  addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn)};
 const context=vm.createContext({document,location:{pathname:'/analytics/statistics'},
  window:{scrollX:0,scrollY:0,scrollTo(){}},MutationObserver:class{observe(){}},setInterval(){},setTimeout,
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
 return {context,posts,bar,details,summary,nodes,replacements:()=>replacements,detach:()=>{mounted=false},manual:()=>button.onclick(),response:value=>response=value,focus:value=>focus=value,dialog:value=>dialog=value,
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
 assert.ok(env.nodes['.refresh-details-body'].innerHTML.includes(`Кнопка: ${period.from} — ${period.to}`));
 await env.manual();
 assert.deepEqual(env.posts,[period]);
});

test('inactive server scheduler is reported honestly',async()=>{
 const env=await setup({status:'idle',last_finished_at:null,server_scheduler:false},{header:true});
 assert.ok(env.nodes['.refresh-status'].textContent.includes('Автообновление сервера не запущено'));
 assert.ok(!env.nodes['.refresh-status'].textContent.includes('Автообновление каждые 5 минут'));
});


test('polling keeps the disclosure and summary nodes while status changes',async()=>{
 const env=await setup(undefined,{header:true});env.details.open=true;
 const summary=env.bar.querySelector('summary');
 env.response({status:'running',last_finished_at:null,sources:{one:{name:'Источник',status:'running'}}});await env.poll();
 assert.equal(env.replacements(),1);assert.equal(env.bar.querySelector('summary'),summary);assert.equal(env.details.open,true);
 assert.equal(env.nodes['.refresh-status'].textContent,'Обновление источников…');
 env.detach();await env.poll();
 assert.equal(env.replacements(),1);assert.equal(env.details.open,true);
});

test('view updates preserve the intended closed state during an interrupted collapse',async()=>{
 const env=await setup(undefined,{header:true});
 env.details.open=true;env.details.dataset.motionExpanded='false';
 const settled=[];env.context.window.fleetMotion={settle:(node,open)=>{settled.push(open);node.open=open}};
 env.response({status:'success',last_finished_at:'2026-10-29T12:00:00+03:00'});await env.poll();
 assert.deepEqual(settled,[false]);assert.equal(env.details.open,false);
});


test('disclosure and scroll changes made during the request are preserved',async()=>{
 const env=await setup(undefined,{header:true});const settled=[],positions=[];
 env.context.window.fleetMotion={settle:(node,open)=>{settled.push(open);node.open=open}};
 env.context.window.scrollTo=position=>positions.push(position.top);
 env.dataHook(async()=>{env.details.open=true;env.details.dataset.motionExpanded='true';env.context.window.scrollY=420});
 env.response({status:'success',last_finished_at:'2026-10-29T12:00:00+03:00'});await env.poll();
 assert.deepEqual(settled,[true]);assert.deepEqual(positions,[420]);
});


test('durable incidents remain visible during an active job and backlog is separate',async()=>{
 const env=await setup({status:'running',server_scheduler:true,alerts:{incidents:[{title:'Источник не обновляется',message:'Сохранённые данные доступны.'}],delivery:{configured:false}},sources:{monitoring:{name:'Спутник',status:'running',catchup:{pending_days:3,from:'2026-08-31'}}}},{header:true});
 assert.equal(env.nodes['.refresh-status'].textContent,'Обновление требует внимания');
 assert.ok(env.nodes['.refresh-alerts'].innerHTML.includes('Сохранённые данные доступны'));
 assert.ok(env.nodes['.refresh-details-body'].innerHTML.includes('Догружаются пропущенные дни: 3'));
 assert.ok(env.nodes['.refresh-details-body'].innerHTML.includes('Внешние уведомления не настроены'));
 env.response({status:'success',alerts:{incidents:[],delivery:{configured:false}}});await env.poll();
 assert.equal(env.nodes['.refresh-alerts'].innerHTML,'');
});

test('unchanged refresh markup preserves DOM enhancements inside alert history',async()=>{
 const env=await setup({status:'idle',alerts:{recent:[{title:'Источник восстановлен',status:'resolved',resolved_at:'2026-11-02T06:00:00Z'}]}},{header:true});
 const body=env.nodes['.refresh-details-body'];
 // motion.js wraps disclosure children after insertion. This must not make
 // refresh.js replace them again and trigger an endless observer cycle.
 body.innerHTML=body.innerHTML.replace('<summary>История предупреждений</summary>','<summary>История предупреждений</summary><div class="disclosure-content">')+'</div>';
 const enhanced=body.innerHTML;
 await env.poll();
 assert.equal(body.innerHTML,enhanced);
});
