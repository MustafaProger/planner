const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/evidence.js','utf8');
const result=(token='review',km=10)=>({token,ready:1,rows:[{row:2,provider_id:'1',km,status:'ready'}]});
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}}
function setup(){
 const requests=[],reads=[],toasts=[];let closes=0,refreshes=0;
 const dialog={open:false,dataset:{}};const nodes={'#dialog':dialog};
 function previewNode(){
  let html='',text='',children={};
  return {get innerHTML(){return html},set innerHTML(value){html=value;text='';children=value.includes('id="mileageCommit"')?{'#mileageCommit':{disabled:false},'#mileageConfirmed':{checked:false}}:{}},
   get textContent(){return text},set textContent(value){text=value;html='';children={}},querySelector:s=>children[s]||null};
 }
 const context=vm.createContext({URLSearchParams,Date,console,csrf:'test',tab:'evidence',from:'2026-08-01',to:'2026-08-31',renderVersion:1,
  esc:String,fmt:String,field:()=>'',table:(headers,rows)=>JSON.stringify(rows),toast:value=>toasts.push(value),
  $:s=>nodes[s]||null,
  modal(){
   if(nodes['#mileageForm'])nodes['#mileageForm'].isConnected=false;
   dialog.open=true;dialog.dataset={};
   const button={disabled:false},input={disabled:false};
   nodes['#mileageForm']={isConnected:true,fields:{file:'file-A',source_as_of:'2026-08-01T11:00:00+03:00',source_ref:'report-A'},querySelector:s=>s==='button'?button:null,querySelectorAll:()=>[input,button],button,input};
   nodes['#mileagePreview']=previewNode();
  },
  FormData:class{constructor(form){this.values=new Map(Object.entries(form?.fields||{}))}entries(){return this.values.entries()}append(k,v){this.values.set(k,v)}set(k,v){this.values.set(k,v)}get(k){return this.values.get(k)}},
  fetch(path,options){const pending=deferred();requests.push({path,body:options.body,resolve:data=>pending.resolve({ok:true,json:async()=>data}),reject:pending.reject});return pending.promise},
  closeModal:async()=>{closes++;dialog.open=false},refresh:async()=>{refreshes++},
  api(){const pending=deferred();reads.push(pending);return pending.promise},
  D:{directories:{drivers:[]},trips:[]},U:{role:'viewer'},within:()=>true
 });
 vm.runInContext(source,context);
 const open=()=>{context.mileageForm();return {form:nodes['#mileageForm'],preview:nodes['#mileagePreview']}};
 return {context,nodes,dialog,requests,reads,toasts,open,stats:()=>({closes,refreshes}),submit:form=>form.onsubmit({preventDefault(){}})};
}

for(const failure of [false,true])test(`late preview ${failure?'error':'success'} cannot alter a reopened form`,async()=>{
 const e=setup(),first=e.open(),pending=e.submit(first.form),second=e.open();
 second.preview.textContent='new form';
 if(failure)e.requests[0].reject(new Error('old error'));else e.requests[0].resolve(result('old'));
 await pending;
 assert.equal(second.preview.textContent,'new form');assert.equal(second.preview.querySelector('#mileageCommit'),null);
 assert.equal(second.form.button.disabled,false);assert.equal(e.toasts.length,0);
});

test('editing during preview invalidates response and permits a new review',async()=>{
 const e=setup(),{form,preview}=e.open(),pending=e.submit(form);
 form.fields.file='file-B';form.oninput();assert.equal(form.button.disabled,false);
 e.requests[0].resolve(result('old'));await pending;
 assert.match(preview.textContent,/Параметры изменились/);assert.equal(preview.querySelector('#mileageCommit'),null);
 const next=e.submit(form);e.requests[1].resolve(result('new'));await next;
 assert.ok(preview.querySelector('#mileageCommit'));assert.equal(e.requests[1].body.get('file'),'file-B');
});

test('older request cannot override latest preview or unlock its pending button',async()=>{
 const e=setup(),{form,preview}=e.open(),first=e.submit(form);
 form.oninput();const second=e.submit(form);
 e.requests[0].resolve(result('old',11));await first;
 assert.equal(form.button.disabled,true);assert.match(preview.textContent,/Проверяем/);
 e.requests[1].resolve(result('new',22));await second;
 assert.ok(preview.innerHTML.includes('22'));assert.equal(form.button.disabled,false);
});

test('confirm uses immutable reviewed upload and stale handlers cannot submit',async()=>{
 const e=setup(),{form,preview}=e.open();const p=e.submit(form);e.requests[0].resolve(result('t1'));await p;
 const stale=preview.querySelector('#mileageCommit');preview.querySelector('#mileageConfirmed').checked=true;
 form.fields.file='file-B';form.oninput();await stale.onclick();assert.equal(e.requests.length,1);
 const next=e.submit(form);e.requests[1].resolve(result('t2'));await next;
 preview.querySelector('#mileageConfirmed').checked=true;
 // Even programmatic field changes without input events cannot alter the already-reviewed upload.
 form.fields.file='file-C';const save=preview.querySelector('#mileageCommit').onclick();
 assert.equal(e.requests[2].body.get('file'),'file-B');assert.equal(e.requests[2].body.get('token'),'t2');
 assert.equal(e.requests[2].body.get('confirmed'),'true');assert.equal(form.input.disabled,true);
 e.requests[2].resolve({applied:1});await save;assert.deepEqual(e.stats(),{closes:1,refreshes:1});
});

for(const failure of [false,true])test(`late confirm ${failure?'failure':'success'} cannot close or refresh another form`,async()=>{
 const e=setup(),first=e.open(),p=e.submit(first.form);e.requests[0].resolve(result());await p;
 first.preview.querySelector('#mileageConfirmed').checked=true;const save=first.preview.querySelector('#mileageCommit').onclick();
 const second=e.open();second.preview.textContent='new editor';
 if(failure)e.requests[1].reject(new Error('old failure'));else e.requests[1].resolve({applied:1});await save;
 assert.deepEqual(e.stats(),{closes:0,refreshes:0});assert.equal(second.preview.textContent,'new editor');
 assert.equal(second.form.input.disabled,false);assert.equal(e.toasts.length,0);
});

test('closed but still-connected dialog ignores late preview and closing animation',async()=>{
 const e=setup(),{form,preview}=e.open(),p=e.submit(form);e.dialog.open=false;
 e.requests[0].resolve(result());await p;assert.equal(preview.querySelector('#mileageCommit'),null);
 const second=e.open(),q=e.submit(second.form);e.dialog.dataset.closing='true';
 e.requests[1].reject(new Error('closed'));await q;assert.equal(second.preview.querySelector('#mileageCommit'),null);
});

test('failed confirm preserves reviewed values and restores its controls for retry',async()=>{
 const e=setup(),{form,preview}=e.open(),p=e.submit(form);e.requests[0].resolve(result());await p;
 preview.querySelector('#mileageConfirmed').checked=true;const commit=preview.querySelector('#mileageCommit');
 const failed=commit.onclick();e.requests[1].reject(new Error('network'));await failed;
 assert.equal(commit.disabled,false);assert.equal(form.input.disabled,false);assert.equal(form.button.disabled,false);
 const retry=commit.onclick();assert.equal(e.requests[2].body.get('file'),'file-A');e.requests[2].resolve({applied:1});await retry;
 assert.deepEqual(e.stats(),{closes:1,refreshes:1});
});

test('page ignores superseded reads and navigation away/back even with same content node',async()=>{
 const e=setup(),target={innerHTML:'initial',querySelectorAll:()=>[]};e.nodes['#content']=target;
 const data={shifts:[],allocation:{totals:{},measurements:[]}};
 const first=e.context.evidencePage();const second=e.context.evidencePage();e.reads[0].resolve(data);await first;
 assert.equal(target.innerHTML,'initial');e.reads[1].resolve(data);await second;assert.match(target.innerHTML,/Километраж/);
 target.innerHTML='navigation destination';const late=e.context.evidencePage();e.context.renderVersion+=2;
 e.reads[2].resolve(data);await late;assert.equal(target.innerHTML,'navigation destination');
});

test('mileage list uses the visible period and ignores inherited hidden vehicle filters',async()=>{
 const e=setup(),target={innerHTML:'',querySelectorAll:()=>[]};e.nodes['#content']=target;
 e.context.within=()=>false; // Statistics page left a vehicle filter; evidence only offers dates.
 e.context.D.trips=[
  {date:'2026-08-10',provider_id:'visible-id',number:'N1',km:10,km_observation:{status:'verified',source_as_of:'2026-08-11',source_ref:'report'}},
  {date:'2026-09-10',provider_id:'outside-period-id',number:'N2',km:20,km_observation:{status:'verified'}}
 ];
 const page=e.context.evidencePage();e.reads[0].resolve({shifts:[],allocation:{totals:{},measurements:[]}});await page;
 assert.ok(target.innerHTML.includes('visible-id'));assert.ok(!target.innerHTML.includes('outside-period-id'));
});
