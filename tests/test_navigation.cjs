const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/main.js','utf8');
function setup(initial='/analytics/dashboard'){
 const entries=[{url:initial,state:null}];let index=0;
 const context=vm.createContext({location:{pathname:entries[0].url},URLSearchParams,Intl,
 document:{querySelector:()=>null},window:{addEventListener:(name,fn)=>context[name]=fn,scrollTo(){}},
 history:{get state(){return entries[index].state},replaceState(state){entries[index].state=structuredClone(state)},pushState(state,_,url){entries.splice(++index);entries.push({state:structuredClone(state),url});context.location.pathname=url}}});
 vm.runInContext(source.slice(0,source.indexOf('async function api'))+`\nconst sections={analytics:['dashboard','reconcile','statistics','comparison','planreport'],planning:['calendar']};let workspaceGroup='vehicle',comparisonMetrics='money',planRows='route';Object.assign(tabs,{planreport:'Сводка плана'});function render(){if(tab==='dashboard')dashboardReturnFilters=null;saveNavigationState()}U={role:'admin'};tab=pageFromURL();car='TEST';`,context);
 return {run:code=>vm.runInContext(code,context),go:offset=>{index+=offset;context.location.pathname=entries[index].url;context.popstate({state:entries[index].state})}};
}
test('date drill-down restores overview and browser forward restores detail',()=>{
 const {run,go}=setup();run("navigate('reconcile',{preserveFilters:true,filters:{from:'2026-08-24',to:'2026-08-24'}})");
 assert.equal(run('from'),'2026-08-24');go(-1);
 assert.equal(run('from'),'2026-08-01');assert.equal(run('to'),'2026-08-31');assert.equal(run('car'),'TEST');go(1);assert.equal(run('from'),'2026-08-24');
});
test('sidebar return restores overview after vehicle drill-down',()=>{
 const {run}=setup();run("navigate('reconcile',{preserveFilters:true,filters:{car:'OTHER'}});navigate('dashboard')");
 assert.equal(run('car'),'TEST');assert.equal(run('to'),'2026-08-31');
});
test('sidebar return restores overview after date drill-down',()=>{
 const {run}=setup();run("navigate('reconcile',{preserveFilters:true,filters:{from:'2026-08-24',to:'2026-08-24'}});navigate('dashboard')");
 assert.equal(run('from'),'2026-08-01');assert.equal(run('to'),'2026-08-31');
});


test('calendar drill-down and Back/Forward preserve source filters, grouping and selected day',()=>{
 const {run,go}=setup('/analytics/comparison');
 run("from='2026-08-01';to='2026-08-31';car='Original car';driver='Original driver';workspaceGroup='pair';comparisonMetrics='distance';navigate('calendar',{preserveFilters:true,filters:{car:'Day car',driver:'',calMonth:'2026-08',calMode:'vehicle',calendarFocusDay:'2026-08-15'}})");
 assert.equal(run('car'),'Day car');assert.equal(run('calendarFocusDay'),'2026-08-15');
 go(-1);
 assert.equal(run('tab'),'comparison');assert.equal(run('workspaceGroup'),'pair');assert.equal(run('comparisonMetrics'),'distance');assert.equal(run('car'),'Original car');assert.equal(run('driver'),'Original driver');assert.equal(run('from'),'2026-08-01');assert.equal(run('to'),'2026-08-31');assert.equal(run('calendarFocusDay'),'');
 go(1);
 assert.equal(run('tab'),'calendar');assert.equal(run('car'),'Day car');assert.equal(run('driver'),'');assert.equal(run('calMonth'),'2026-08');assert.equal(run('calMode'),'vehicle');assert.equal(run('calendarFocusDay'),'2026-08-15');
});

test('plan summary grouping survives ordinary navigation and browser Back',()=>{
 const {run,go}=setup('/analytics/planreport');
 run("workspaceGroup='route';from='2027-01-01';to='2027-03-31';navigate('statistics')");
 go(-1);assert.equal(run('tab'),'planreport');assert.equal(run('workspaceGroup'),'route');assert.equal(run('from'),'2027-01-01');assert.equal(run('to'),'2027-03-31');
});
