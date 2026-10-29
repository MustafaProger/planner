const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/main.js','utf8');
function setup(){
 const entries=[{url:'/analytics/dashboard',state:null}];let index=0;
 const context=vm.createContext({location:{pathname:entries[0].url},URLSearchParams,Intl,
 document:{querySelector:()=>null},window:{addEventListener:(name,fn)=>context[name]=fn,scrollTo(){}},
 history:{get state(){return entries[index].state},replaceState(state){entries[index].state=structuredClone(state)},pushState(state,_,url){entries.splice(++index);entries.push({state:structuredClone(state),url});context.location.pathname=url}}});
 vm.runInContext(source.slice(0,source.indexOf('async function api'))+`\nconst sections={analytics:['dashboard','reconcile','statistics']};function render(){if(tab==='dashboard')dashboardReturnFilters=null;saveNavigationState()}U={role:'admin'};tab='dashboard';car='TEST';`,context);
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
