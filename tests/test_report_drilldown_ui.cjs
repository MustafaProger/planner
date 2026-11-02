const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}}
function setup(){
 const nodes={},requests=[],bodies=[];
 const dialog={open:false,dataset:{},close(){this.open=false},querySelector(selector){return bodies.at(-1)?.selector===selector||selector==='[data-report-details],[data-reconcile-details]'?bodies.at(-1):null}};
 nodes['#dialog']=dialog;
 const document={querySelector:s=>nodes[s]||null,querySelectorAll:()=>[],getElementById:()=>null,addEventListener(){}};
 const context=vm.createContext({Intl,URLSearchParams,Date,document,location:{pathname:'/analytics/comparison'},history:{state:null,replaceState(){}},window:{addEventListener(){}},MutationObserver:class{observe(){}},setTimeout,clearTimeout});
 for(const name of ['main','workspace','ui'])vm.runInContext(fs.readFileSync('app/static/'+name+'.js','utf8'),context);
 context.fakeApi=url=>{const pending=deferred();requests.push({url,...pending});return pending.promise};
 context.fakeModal=html=>{
  if(bodies.length)bodies.at(-1).isConnected=false;
  dialog.open=true;dialog.dataset={};let markup='';
  const body={selector:html.includes('data-reconcile-details')?'[data-reconcile-details]':'[data-report-details]',isConnected:true,buttons:{},
   get innerHTML(){return markup},set innerHTML(value){markup=value;this.buttons={};for(const selector of ['[data-detail-retry]','#detail-calendar'])if(value.includes(selector==='#detail-calendar'?'id="detail-calendar"':'data-detail-retry'))this.buttons[selector]={};},
   querySelector(selector){return this.buttons[selector]||null},querySelectorAll(){return []}};
  body.innerHTML=html;bodies.push(body);
 };
 context.drawResult=result=>'result:'+result.value;
 const run=code=>vm.runInContext(code,context);
 run("api=fakeApi;modal=fakeModal;tab='comparison';renderVersion=1;U={role:'admin',vehicles:[]};D={plans:[],trips:[],statuses:[],directories:{}};");
 return {run,context,nodes,requests,bodies,dialog};
}

for(const stale of ['reopen','navigation','closing'])for(const failed of [false,true])test(`detail ignores late ${failed?'error':'success'} after ${stale}`,async()=>{
 const env=setup(),first=env.run("openReadOnlyDetail('workspace/report/details?row=one','one','report',drawResult)");
 let second;
 if(stale==='reopen')second=env.run("openReadOnlyDetail('workspace/report/details?row=two','two','report',drawResult)");
 if(stale==='navigation')env.run('renderVersion+=2'); // leave and return to the same tab
 if(stale==='closing')env.dialog.dataset.closing='true';
 const active=env.bodies.at(-1),before=active.innerHTML;
 if(failed)env.requests[0].reject(Error('old error'));else env.requests[0].resolve({value:'old'});
 await first;assert.equal(active.innerHTML,before);
 if(second){env.requests[1].resolve({value:'new'});await second;assert.equal(active.innerHTML,'result:new')}
});

test('detail retry keeps the immutable query and escapes the server error',async()=>{
 const env=setup(),query='workspace/report/details?from=2026-08-01&vehicle=A%26B&group=pair&row=A+%C2%B7+B';
 env.context.query=query;
 const first=env.run("openReadOnlyDetail(query,'test','report',drawResult)");
 env.requests[0].reject(Error('<script>bad</script>'));await first;
 assert.match(env.bodies[0].innerHTML,/&lt;script&gt;bad&lt;\/script&gt;/);
 env.run("from='2027-01-01';workspaceGroup='driver';car='Other'");
 const retry=env.bodies[0].querySelector('[data-detail-retry]').onclick();
 assert.equal(env.requests[1].url,query);env.requests[1].resolve({value:'recovered'});await retry;
 assert.equal(env.bodies[0].innerHTML,'result:recovered');
});

test('report row uses the captured period, grouping and filters, not later globals',async()=>{
 const env=setup(),row={dataset:{row:'0'},setAttribute(){}};
 env.nodes['#content']={innerHTML:'',querySelectorAll:selector=>selector==='[data-row]'?[row]:[]};
 env.nodes['#export']={};env.nodes['[name=workspaceGroup]']={};env.nodes['[name=comparisonMetrics]']={};
 const opened=[];env.context.captureDetail=(query,name)=>opened.push({query,name});
 env.run("openWorkspaceDetail=captureDetail;from='2026-08-01';to='2026-08-31';car='A & B';driver='Driver';workspaceGroup='pair'");
 const pending=env.run("workspaceReport('comparison')");
 env.requests[0].resolve({rows:[{name:'A · B · Driver',state:'test',delta_reasons:{}}],plan_complete:false,fact_complete:false});await pending;
 env.run("from='2027-02-01';car='Other';driver='Other';workspaceGroup='vehicle'");row.onclick();
 const query=new URLSearchParams(opened[0].query);
 assert.equal(query.get('from'),'2026-08-01');assert.equal(query.get('to'),'2026-08-31');assert.equal(query.get('vehicle'),'A & B');assert.equal(query.get('driver'),'Driver');assert.equal(query.get('group'),'pair');assert.equal(opened[0].name,'A · B · Driver');
 assert.match(env.nodes['#content'].innerHTML,/tabindex="0"/);
});

test('out-of-order grouping responses cannot replace a newer report',async()=>{
 const env=setup();env.nodes['#content']={innerHTML:'',querySelectorAll:()=>[]};env.nodes['#export']={};env.nodes['[name=workspaceGroup]']={};
 const first=env.run("workspaceGroup='vehicle';workspaceReport('plans')"),second=env.run("workspaceGroup='route';workspaceReport('plans')");
 env.requests[1].resolve({rows:[{name:'New route'}],excluded:0,unassigned:0});await second;
 env.requests[0].resolve({rows:[{name:'Old car'}],excluded:0,unassigned:0});await first;
 assert.match(env.nodes['#content'].innerHTML,/New route/);assert.doesNotMatch(env.nodes['#content'].innerHTML,/Old car/);
});

test('detail edits use the shown record version and enforce existing roles and vehicles',()=>{
 const env=setup(),shown={id:'plan-1',vehicle:'A',revision:3},button={dataset:{kind:'plans',record:'plan-1'},remove(){this.removed=true}},root={querySelectorAll:()=>[button]},opened=[];
 env.context.root=root;env.context.records={plans:[shown]};env.context.capturePlan=row=>opened.push(row);
 env.run("planForm=capturePlan;U={role:'logist',vehicles:['A']};D.plans=[{id:'plan-1',revision:9}];bindDetailRecords(root,records,()=>true)");
 button.onclick();assert.equal(opened[0].revision,3);assert.equal(opened[0],shown);
 for(const [role,vehicles,kind,origin,expected] of [['viewer',['A'],'plans','manual',false],['logist',['B'],'plans','manual',false],['logist',['A'],'plans','manual',true],['logist',['A'],'trips','api',false],['logist',['A'],'trips','manual',true],['admin',[],'trips','api',true]]){
  env.context.user={role,vehicles};env.context.record={id:'id',vehicle:'A',origin};env.context.kind=kind;
  assert.equal(env.run('U=user;canEditDetailRecord(record,kind)'),expected,`${role} ${kind} ${origin}`);
 }
});

function reconcileResult(){return {vehicle:'A & B',date:'2026-08-15',summary:{tt_km:null,sat_km:80,delta_km:null,tt_hours:2,sat_engine_hours:0,sat_hours:3,state:'Нет пробега ТТ'},trips:[],other_trips:[],satellite:[{date:'2026-08-15',km:80,engine_hours:0,source:'API'}],satellite_raw:[{start:'2026-08-15T00:00',end:'2026-08-15T03:00',km:70,hours:3,source:'Excel',metric_usage:{km:'replaced_by_api',hours:'used'}}],metric_usage:{km:{value:80,source:'API',excel_role:'replaced_by_api'},hours:{value:3,source:'Excel',excel_role:'used'},engine_hours:{value:0,source:'API',excel_role:'unavailable'}}}}

test('source detail separates effective metrics from raw Excel and keeps unknowns and zero',()=>{
 const env=setup();env.context.result=reconcileResult();const html=env.run('reconcileDetailMarkup(result)');
 assert.match(html,/data-detail-satellite>/);assert.match(html,/data-detail-satellite-raw>/);assert.match(html,/Заменено показателем API/);assert.match(html,/Учтено из Excel/);assert.match(html,/<td>0<\/td>/);assert.match(html,/<td>—<\/td>/);assert.match(html,/не складываются/);assert.doesNotMatch(html,/<td>150<\/td>/);
});

for(const moved of [false,true])test(`calendar drill-down ${moved?'ignores navigation during close':'preserves captured vehicle and day from dashboard'}`,async()=>{
 const env=setup(),navigations=[],close=deferred();env.context.captureNavigation=(key,options)=>navigations.push({key,options});env.context.closeLater=()=>close.promise;
 env.run("tab='dashboard';navigate=captureNavigation;closeModal=closeLater");env.context.row={vehicle:'A & B',date:'2026-08-15'};
 const opened=env.run('openReconcileDetail(row)');env.requests[0].resolve(reconcileResult());await opened;
 const click=env.bodies[0].querySelector('#detail-calendar').onclick();
 if(moved)env.run('renderVersion+=2'); // away and back, same tab must still be stale
 env.dialog.open=false;close.resolve();await click;
 assert.equal(navigations.length,moved?0:1);
 if(!moved){assert.equal(navigations[0].key,'calendar');assert.equal(navigations[0].options.preserveFilters,true);assert.equal(navigations[0].options.filters.car,'A & B');assert.equal(navigations[0].options.filters.calendarFocusDay,'2026-08-15');assert.equal(navigations[0].options.filters.calMonth,'2026-08')}
});

test('late grouped report cannot rebind an open detail edit to a newer global revision',async()=>{
 const env=setup(),opened=[],button={dataset:{kind:'plans',record:'plan-1'},remove(){throw Error('authorized button must stay')}};
 env.nodes['#content']={innerHTML:'',querySelectorAll:()=>[]};
 env.nodes['#export']={};env.nodes['[name=workspaceGroup]']={};env.nodes['[name=comparisonMetrics]']={};
 // This button belongs to the dialog, so a document-wide bind would find it.
 env.context.document.querySelectorAll=selector=>selector==='[data-record]'?[button]:[];
 env.context.capturePlan=record=>opened.push(record.revision);
 env.run("planForm=capturePlan;D.plans=[{id:'plan-1',vehicle:'A',revision:9}]");
 const report=env.run("workspaceGroup='driver';workspaceReport('comparison')");
 const detail=env.run("openWorkspaceDetail('mode=comparison&group=vehicle&from=2026-08-01&to=2026-08-31','A')");
 env.bodies[0].querySelectorAll=selector=>selector==='[data-record]'?[button]:[];
 env.requests[1].resolve({mode:'comparison',name:'A',scope:{from:'2026-08-01',to:'2026-08-31'},summary:{},plans:[{id:'plan-1',vehicle:'A',revision:3}],trips:[],excluded_plans:[],excluded_trips:[]});
 await detail;button.onclick();
 env.requests[0].resolve({rows:[],plan_complete:false,fact_complete:false});await report;
 button.onclick();
 assert.deepEqual(opened,[3,3],'editing keeps the version actually shown before and after the pending report completes');
});
