const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(){
 const context=vm.createContext({Intl,URLSearchParams,Date,location:{pathname:'/data/orders'},
 document:{querySelector:()=>null,getElementById:()=>null,addEventListener(){}},
 window:{addEventListener(){}},MutationObserver:class{observe(){}},setTimeout,clearTimeout});
 for(const name of ['main','workspace','ui','planviews'])vm.runInContext(fs.readFileSync('app/static/'+name+'.js','utf8'),context);
 return {context,run:code=>vm.runInContext(code,context)};
}
test('source data has one menu location and legacy connection URLs remain valid',()=>{
 const {run}=setup();
 for(const [key,path] of Object.entries({orders:'/data/orders',neftmdata:'/data/neftmdata',rosneftdata:'/data/rosneftdata',monitoringdata:'/data/monitoringdata',connections:'/settings/connections',quality:'/control/quality',guide:'/help/guide',transtrade:'/integrations/transtrade'}))assert.equal(run(`pagePath('${key}')`),path);
 assert.equal(run('new Set(Object.values(sections).flat()).size'),run('Object.values(sections).flat().length'));
 for(const path of ['/data/connections','/data/quality','/integrations/neftm']){run(`location.pathname='${path}'`);assert.equal(run('pageFromURL()'),path.split('/').at(-1))}
});
test('API missing metrics are a limitation, while conflicts stay actionable',()=>{
 const {run}=setup();
 assert.equal(run("qualityKind({issue:'API: есть отсутствующие показатели; не равны нулю'})"),'missing');
 assert.equal(run("qualityKind({issue:'Есть версия API с тем же ID. Локальная заявка сохранена'})"),'source');
 assert.equal(run("qualityKind({issue:'Не вернулась из API — прежняя запись сохранена'})"),'source');
 assert.equal(run("qualityKind({issue:'API: есть отсутствующие показатели; не равны нулю',record:{km:null,revenue:null,payout:100}})"),'source');
});
test('automatic latest snapshot changes do not change selected historical fuel period',async()=>{
 const {context,run}=setup();const calls=[],draws=[];
 context.panel={isConnected:true};context.snapshot={from:'2026-08-01',to:'2026-08-31',rows:[{dateRec:'2026-08-10T09:00:00'}]};
 context.fakeApi=async path=>{calls.push(path);return path==='neftm'?{configured:true,snapshot:{from:'2026-10-01',to:'2026-10-29',rows:[{dateRec:'2026-10-29T09:00:00'}]}}:context.snapshot};
 context.capture=(panel,provider,configured,snapshot)=>draws.push(snapshot);
 context.document.querySelector=()=>context.panel;run('api=fakeApi;drawFuelPanel=capture;');
 await run("loadFuelPanel('neftm')");await run("loadFuelPanel('neftm')");
 assert.ok(calls.filter(x=>x.startsWith('fuel-history')).every(x=>x.includes('from=2026-08-01&to=2026-08-31')));
 assert.equal(draws.length,2);assert.ok(draws.every(x=>x.from==='2026-08-01'&&x.rows[0].dateRec.startsWith('2026-08')));
});
