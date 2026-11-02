const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(){
 const nodes={};const document={querySelector:s=>nodes[s]||null,querySelectorAll:()=>[],getElementById:()=>null,addEventListener(){}};
 const context=vm.createContext({Intl,URLSearchParams,Date,location:{pathname:'/analytics/statistics'},document,window:{addEventListener(){}},MutationObserver:class{observe(){}},setTimeout,clearTimeout});
 for(const name of ['main','workspace','ui'])vm.runInContext(fs.readFileSync('app/static/'+name+'.js','utf8'),context);
 return {context,nodes,run:code=>vm.runInContext(code,context)};
}
test('statistics presents filtered API rows consistently in table, details and CSV',async()=>{
 const {context,nodes,run}=setup();const clicked={dataset:{row:'0'}};nodes['#content']={innerHTML:'',querySelectorAll:()=>[clicked]};
 for(const key of ['#group','#statisticsView','#attributeFilters','#export'])nodes[key]={};
 context.result={rows:[{name:'Газель',records:2,trips:2,average_record_revenue:1500,average_trip_revenue:1500,revenue_per_trip:1500,revenue:3000}],totals:{name:'Всего',records:2,trips:2,revenue:3000,average_trip_revenue:1500},trips:[{id:'1',vehicle_brand:'Газель'},{id:'2',vehicle_brand:'Газель'},{id:'3',vehicle_brand:'Другая'}],filter_options:{vehicle_brand:['Газель','Другая']},attribute_basis:'Текущий справочник',average_formulas:{average_trip_revenue:'Выручка рейсов / рейсы'}};
 const requests=[],exports=[],details=[];context.fakeApi=async q=>{requests.push(q);return context.result};context.captureCsv=x=>exports.push(x);context.captureTrips=(rows,title)=>details.push({rows,title});
 run("api=fakeApi;csv=captureCsv;showTrips=captureTrips;group='vehicle_brand';statisticsView='averages';attributeFilters.vehicle_brand='Газель';");
 await run('statistics()');nodes['#export'].onclick();clicked.onclick();
 assert.match(requests[0],/vehicle_brand=/);assert.ok(nodes['#content'].innerHTML.includes('Средняя выручка рейса'));
 assert.equal(exports[0][0]['Средняя выручка рейса, ₽'],1500);assert.equal(exports[0][0]['Атрибуты'],'Текущий справочник');
 assert.deepEqual(Array.from(details[0].rows,r=>r.id),['1','2']);
 run("const saved=filterState();attributeFilters.vehicle_brand='';statisticsView='totals';restoreFilters(saved)");
 assert.equal(run('attributeFilters.vehicle_brand'),'Газель');assert.equal(run('statisticsView'),'averages');
});
test('comparison exposes all six API deltas with positive, negative, zero and missing reasons',()=>{
 const {context,run}=setup();context.row={name:'Машина',state:'Сопоставимо',plan_trips:2,fact_trips:2,delta_trips:0,plan_days:2,fact_days:1,delta_days:-1,plan_revenue:1000,fact_revenue:1100,delta_revenue:100,plan_payout:100,fact_payout:90,delta_payout:-10,plan_km:100,fact_km:null,delta_km:null,plan_hours:4,fact_hours:5,delta_hours:1,delta_reasons:{km:'Нет полного показателя факта'}};
 assert.deepEqual(Array.from(run("comparisonMetrics='money';comparisonCells(row)")).slice(1,7),['1 000','1 100','+100','100','90','-10']);
 assert.deepEqual(Array.from(run("comparisonMetrics='work';comparisonCells(row)")).slice(1,7),['2','2','0','2','1','-1']);
 const distance=Array.from(run("comparisonMetrics='distance';comparisonCells(row)"));assert.match(distance[3],/Нет полного показателя факта/);assert.equal(distance[6],'+1');
});
test('delete uses revision and token shown before a background dataset change, then offers explicit reload on conflict',async()=>{
 const {context,run}=setup();const button={dataset:{delete:'status-1'}};context.document.querySelectorAll=()=>[button];
 const calls=[],conflicts=[];context.fakeApi=async(path,opts)=>{calls.push({path,body:JSON.parse(opts.body)});throw Object.assign(Error('Данные изменились'),{status:409})};context.captureConflict=e=>conflicts.push(e.message);
 run("D={statuses:[{id:'status-1',revision:1,delete_token:'old-group'}],plans:[],trips:[]};api=fakeApi;showWriteConflict=captureConflict;bindDelete();D.statuses[0]={id:'status-1',revision:2,delete_token:'new-group'};");
 await button.onclick();assert.deepEqual(calls,[{path:'manual/status-1',body:{revision:1,delete_token:'old-group'}}]);assert.deepEqual(conflicts,['Данные изменились']);
});

test('review assignments direct the operator to planner, not source connection',()=>{
 const {run}=setup();assert.equal(run("qualityKind({issue:'Назначение требует проверки: уточните ресурс'})"),'review');assert.equal(run('qualityInfo.review[3]'),'planner');
});

test('evidence has a visible editable period without hidden car or driver filters',()=>{
 const {run}=setup();
 run("from='2027-02-01';to='2027-03-31'");
 const fields=run("reportFilterFields('evidence')");
 assert.match(fields,/id="from" type="date" value="2027-02-01"/);
 assert.match(fields,/id="to" type="date" value="2027-03-31"/);
 assert.equal((fields.match(/<input/g)||[]).length,2);
 assert.doesNotMatch(fields,/<select/);
});
