// Deliberate failures prove runner deadlines and browser cleanup. Only child
// PIDs observed in this launch are inspected; no user browser/profile is used.
const {spawn,spawnSync}=require('node:child_process');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');

const root=path.resolve(__dirname,'..');
const results=[];
const alive=pid=>{try{process.kill(pid,0);return true}catch(error){if(error.code==='ESRCH')return false;throw error}};

async function probe(mode,expected){
 const started=performance.now();
 const child=spawn(process.execPath,[require.resolve('@playwright/test/cli'),'test','--config='+path.join(root,'playwright.config.cjs'),'--project=desktop','--timeout=10000','--global-timeout=15000'],{
  cwd:root,detached:process.platform!=='win32',stdio:['ignore','pipe','pipe'],
  env:{...process.env,SIDEBAR_FAILURE_PROBE:mode,DEBUG:'pw:browser',FORCE_COLOR:'0'},
 });
 let output='',timedOut=false;
 const browserPids=new Set();
 const capture=chunk=>{
  output+=chunk.toString();
  for(const match of output.matchAll(/<launched> pid=(\d+)/g))browserPids.add(Number(match[1]));
 };
 child.stdout.on('data',capture);child.stderr.on('data',capture);
 const timer=setTimeout(()=>{
  timedOut=true;
  // Emergency fallback is scoped to this runner and its reported browsers.
  // Normal success must not use it: assertions below require graceful exits.
  for(const pid of [...browserPids,child.pid]){
   if(!alive(pid))continue;
   if(process.platform==='win32')spawnSync('taskkill',['/pid',String(pid),'/T','/F']);
   else {try{process.kill(-pid,'SIGKILL')}catch{try{process.kill(pid,'SIGKILL')}catch{}}}
  }
 },20000);
 const {code,signal}=await new Promise((resolve,reject)=>{
  child.once('error',reject);child.once('close',(code,signal)=>resolve({code,signal}));
 }).finally(()=>clearTimeout(timer));
 const elapsedMs=Math.round(performance.now()-started);
 const log=path.join(root,'.local','sidebar-'+mode+'-probe.log');
 fs.mkdirSync(path.dirname(log),{recursive:true});fs.writeFileSync(log,output);
 assert.equal(timedOut,false,'runner exceeded the independent 20-second deadline');
 assert.equal(code,1,`probe must fail normally, not crash or pass (signal ${signal})`);
 assert.match(output,expected,'failure must be the intended regression, not a setup failure');
 assert.ok(browserPids.size>0,'browser launch PID must be recorded');
 for(const pid of browserPids){
  assert.equal(alive(pid),false,`owned browser ${pid} survived runner cleanup`);
  assert.ok(output.includes(`[pid=${pid}] <process did exit:`),`browser ${pid} exit must be recorded`);
 }
 const result={mode,expectedFailure:true,exitCode:code,elapsedMs,browserCount:browserPids.size,allBrowsersExited:true,emergencyKillUsed:timedOut};
 results.push(result);console.log(JSON.stringify(result));
}

(async()=>{
 await probe('selector',/locator\.click: Timeout 3000ms exceeded[\s\S]*missing-probe/);
 await probe('scroll-reset',/sidebar scroll after navigation/);
 console.log(JSON.stringify({probes:results.length,passed:true}));
})().catch(error=>{console.error(error);process.exitCode=1});
