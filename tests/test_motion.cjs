const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/motion.js','utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));

// A small layout/WAAPI fixture: animations control the measured box and computed
// opacity until cancelled. Tests advance time explicitly, so reversal assertions
// detect a jump to natural/open height rather than simply checking CSS constants.
class Animation {
 constructor(owner,frames,options){this.owner=owner;this.frames=frames;this.options=options;this.progress=0;this.playState='running'}
 get finished(){
  if(!this.promise)this.promise=new Promise((resolve,reject)=>{this.resolve=resolve;this.reject=reject;if(this.playState==='finished')resolve();if(this.playState==='idle')reject(Object.assign(new Error('cancelled'),{name:'AbortError'}))});
  return this.promise;
 }
 value(property){
  if(!['running','finished'].includes(this.playState)||!(property in this.frames[0]))return undefined;
  const [first,last]=[this.frames[0][property],this.frames.at(-1)[property]];
  return typeof first==='number'||property==='height'?parseFloat(first)+(parseFloat(last)-parseFloat(first))*this.progress:this.progress===1?last:first;
 }
 cancel(){this.playState='idle';this.reject?.(Object.assign(new Error('cancelled'),{name:'AbortError'}))}
 finish(){this.progress=1;this.playState='finished';this.resolve?.()}
}
class Element {
 constructor(tag='div',height=0){
  this.tagName=tag.toUpperCase();this.nodeType=1;this.childNodes=[];this.parentElement=null;this.className='';this.dataset={};this.open=false;this.inert=false;this.height=height;this.animations=[];this.events=[];this.extraBox=0;
  this.style={removeProperty:name=>delete this.style[name]};
  this.classList={contains:c=>this.className.split(/\s+/).includes(c),add:c=>{if(!this.classList.contains(c))this.className=(this.className+' '+c).trim()},remove:c=>{this.className=this.className.split(/\s+/).filter(v=>v!==c).join(' ')}};
 }
 get children(){return this.childNodes.filter(n=>n.nodeType===1)}
 append(...nodes){for(const n of nodes){if(n.parentElement)n.parentElement.childNodes=n.parentElement.childNodes.filter(x=>x!==n);n.parentElement=this;this.childNodes.push(n)}}
 matches(selector){return selector.split(',').some(part=>{const [tag,...classes]=part.trim().split('.');return (!tag||tag.toUpperCase()===this.tagName)&&classes.every(c=>this.classList.contains(c))})}
 closest(selector){for(let n=this;n;n=n.parentElement)if(n.matches(selector))return n;return null}
 querySelectorAll(selector){if(selector.startsWith(':scope > '))return this.children.filter(n=>n.matches(selector.slice(9)));return this.children.flatMap(n=>[...(n.matches(selector)?[n]:[]),...n.querySelectorAll(selector)])}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null}
 dispatchEvent(event){this.events.push(event);return true}
 animate(frames,options){const a=new Animation(this,frames,options);this.animations.push(a);return a}
 getAnimations(){return this.animations.filter(a=>a.playState==='running')}
 animated(property){for(const a of this.animations.slice().reverse()){const value=a.value(property);if(value!==undefined)return value}}
 getBoundingClientRect(){
  const animated=this.animated('height');
  const natural=this.tagName==='DETAILS'?this.extraBox+this.children.filter(n=>this.open||n.tagName==='SUMMARY').reduce((sum,n)=>sum+n.getBoundingClientRect().height,0):this.height||this.children.reduce((sum,n)=>sum+n.getBoundingClientRect().height,0);
  return {height:animated??natural,width:300,x:0,y:0};
 }
 close(){this.open=false;this.closes=(this.closes||0)+1}
}
function setup({reduce=false}={}){
 const app=new Element(),dialog=new Element('dialog',400),listeners={},mediaListeners=[];
 const media={matches:reduce,addEventListener:(_,fn)=>mediaListeners.push(fn)};
 const document={getElementById:id=>({app,dialog}[id]||null),createElement:tag=>new Element(tag),querySelector:()=>null,querySelectorAll:selector=>[...app.querySelectorAll(selector),...dialog.querySelectorAll(selector)],addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn)};
 const context=vm.createContext({document,window:{addEventListener(){},removeEventListener(){}},location:{pathname:'/test'},matchMedia:()=>media,
  MutationObserver:class{observe(){}},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}},
  getComputedStyle:el=>({opacity:String(el.animated('opacity')??1),transform:el.animated('transform')??'none',paddingTop:el.extraBox?'8px':'0px',paddingBottom:el.extraBox?'8px':'0px',borderTopWidth:el.extraBox?'1px':'0px',borderBottomWidth:el.extraBox?'1px':'0px'}),
  animateSurface(){},closeModal(){},positionMonthPill(){}
 });
 vm.runInContext(source,context);
 function disclosure(open=false){const details=new Element('details'),summary=new Element('summary',40),body=new Element('div',200);details.extraBox=18;details.open=open;details.append(summary,body);app.append(details);return {details,summary,body}}
 return {context,app,dialog,disclosure,motion:context.window.fleetMotion,
  reduce(value){media.matches=value;mediaListeners.forEach(fn=>fn())},
  click(target,detail=1){const event={target,detail,defaultPrevented:false,preventDefault(){this.defaultPrevented=true}};(listeners.click||[]).forEach(fn=>fn(event));return event}
 };
}

test('settle creates one content wrapper and preserves summary/body identity and focusability',()=>{
 const env=setup(),{details,summary,body}=env.disclosure();
 env.motion.settle(details,false);
 const content=details.querySelector(':scope > .disclosure-content');
 assert.equal(details.children.length,2);assert.equal(details.children[0],summary);assert.equal(content.children[0],body);assert.equal(content.inert,true);
 env.motion.settle(details,true);env.motion.settle(details,true);
 assert.equal(details.querySelector(':scope > .disclosure-content'),content);assert.equal(details.children.length,2);assert.equal(content.inert,false);assert.equal(details.open,true);
});

test('interrupted open-close-open continues from the visible height and opacity',async()=>{
 const env=setup(),{details}=env.disclosure();env.motion.toggle(details,true);
 const content=details.querySelector(':scope > .disclosure-content'),first=details.animations.at(-1),firstFade=content.animations.at(-1);
 first.progress=.4;firstFade.progress=.4;assert.equal(details.getBoundingClientRect().height,138);
 env.motion.toggle(details,false);
 const closing=details.animations.at(-1),closingFade=content.animations.at(-1);
 assert.equal(first.playState,'idle');assert.equal(closing.frames[0].height,'138px');assert.equal(closing.frames[1].height,'58px');assert.equal(content.inert,true);
 closing.progress=.5;closingFade.progress=.5;assert.equal(details.getBoundingClientRect().height,98);
 env.motion.toggle(details,true);
 const reopening=details.animations.at(-1),reopenFade=content.animations.at(-1);
 assert.equal(closing.playState,'idle');assert.equal(reopening.frames[0].height,'98px');assert.equal(reopening.frames[1].height,'258px');assert.equal(reopenFade.frames[0].opacity,.2);assert.equal(content.inert,false);
 reopening.finish();await flush();
 assert.equal(details.open,true);assert.equal(details.getBoundingClientRect().height,258);assert.equal(details.classList.contains('is-disclosing'),false);assert.equal(details.dataset.motionExpanded,'true');
});

test('closing body becomes inert before animation ends; completion restores native closed state',async()=>{
 const env=setup(),{details}=env.disclosure(true);env.motion.toggle(details,false);
 assert.equal(details.open,true);assert.equal(details.dataset.motionExpanded,'false');assert.equal(details.querySelector('.disclosure-content').inert,true);
 details.animations.at(-1).finish();await flush();assert.equal(details.open,false);assert.equal(details.getBoundingClientRect().height,58);
});

test('keyboard summary activation is instant and interactive children retain their own action',()=>{
 const env=setup(),{details,summary}=env.disclosure();
 assert.equal(env.click(summary,0).defaultPrevented,true);assert.equal(details.open,true);assert.equal(details.animations.length,0);
 env.click(summary,0);assert.equal(details.open,false);assert.equal(details.querySelector('.disclosure-content').inert,true);
 const button=new Element('button',20);summary.append(button);
 assert.equal(env.click(button).defaultPrevented,false);assert.equal(details.open,false);
});

test('reduced motion is immediate and a preference change settles an in-flight close',async()=>{
 const reduced=setup({reduce:true}),a=reduced.disclosure();reduced.motion.toggle(a.details,true);assert.equal(a.details.open,true);assert.equal(a.details.animations.length,0);
 const env=setup(),{details}=env.disclosure(true);env.motion.toggle(details,false);const animation=details.animations.at(-1);animation.progress=.2;
 env.reduce(true);await flush();assert.equal(animation.playState,'idle');assert.equal(details.open,false);assert.equal(details.dataset.motionExpanded,'false');assert.equal(details.classList.contains('is-disclosing'),false);
});

test('refresh settle cancels pending transitions and stale completion cannot undo restored state',async()=>{
 const env=setup(),{details,summary,body}=env.disclosure(true);env.motion.toggle(details,false);const closing=details.animations.at(-1);
 env.motion.settle(details,true);closing.finish();await flush();
 assert.equal(details.open,true);assert.equal(details.querySelector('summary'),summary);assert.equal(details.querySelector('.disclosure-content').children[0],body);assert.equal(details.dataset.motionExpanded,'true');assert.equal(details.querySelector('.disclosure-content').inert,false);
});

test('new dialog entry interrupts exit without closing or cancelling the replacement',async()=>{
 const env=setup(),dialog=env.dialog;dialog.open=true;env.context.animateSurface(dialog);
 const entering=dialog.animations.at(-1);entering.progress=.5;
 const closingPromise=env.context.closeModal(),closing=dialog.animations.at(-1);
 assert.equal(entering.playState,'idle');assert.equal(dialog.dataset.closing,'true');
 await env.context.closeModal();assert.equal(dialog.animations.at(-1),closing,'double close must not add a competing animation');
 env.context.animateSurface(dialog);const replacement=dialog.animations.at(-1);await closingPromise;
 assert.equal(dialog.open,true);assert.equal(replacement.playState,'running');assert.equal(dialog.dataset.closing,undefined);
 const completion=env.context.closeModal();dialog.animations.at(-1).finish();await completion;
 assert.equal(dialog.open,false);assert.equal(dialog.closes,1);assert.equal(dialog.dataset.closing,undefined);
});
