/* Restore compact, interruptible motion without changing application records. */
(() => {
 const media=matchMedia('(prefers-reduced-motion: reduce)');
 const ease='cubic-bezier(.23,1,.32,1)';
 const active=new WeakMap();
 function prepare(details){
  const summary=details.querySelector(':scope > summary');
  if(!summary)return null;
  let content=details.querySelector(':scope > .disclosure-content');
  if(!content){
   content=document.createElement('div');content.className='disclosure-content';
   const children=[...details.childNodes].filter(n=>n!==summary);
   content.append(...children);details.append(content);
  }
  details.classList.add('motion-details');
  if(!active.has(details))details.dataset.motionExpanded=String(details.open);
  return {summary,content};
 }
 function finish(details,open){
  const running=active.get(details);
  if(running){active.delete(details);running.height.cancel();running.fade.cancel()}
  details.open=open;details.dataset.motionExpanded=String(open);
  details.classList.remove('is-disclosing');details.style.removeProperty('height');
  const content=details.querySelector(':scope > .disclosure-content');
  if(content)content.inert=!open;
 }
 function settle(details,open){prepare(details);finish(details,open)}
 function toggle(details,requested,options={}){
  const parts=prepare(details);if(!parts)return;
  const previous=active.get(details),open=requested??!(previous?.open??details.open);
  const start=details.getBoundingClientRect().height;
  const startOpacity=details.open?Number(getComputedStyle(parts.content).opacity):0;
  if(previous){active.delete(details);previous.height.cancel();previous.fade.cancel()}
  details.dataset.motionExpanded=String(open);
  details.dispatchEvent(new CustomEvent('disclosurechange',{detail:{open}}));
  if(media.matches||options.animate===false||typeof details.animate!=='function'){
   finish(details,open);return;
  }
  details.open=true;parts.content.inert=!open;details.style.removeProperty('height');
  const styles=getComputedStyle(details);
  const closedHeight=parts.summary.getBoundingClientRect().height+['paddingTop','paddingBottom','borderTopWidth','borderBottomWidth'].reduce((n,k)=>n+parseFloat(styles[k]||0),0);
  const end=open?details.getBoundingClientRect().height:closedHeight;
  details.classList.add('is-disclosing');
  const height=details.animate([{height:start+'px'},{height:end+'px'}],{duration:200,easing:ease,fill:'both'});
  const fade=parts.content.animate([{opacity:startOpacity},{opacity:open?1:0}],{duration:160,easing:ease,fill:'both'});
  const running={open,height,fade};active.set(details,running);
  height.finished.then(()=>{if(active.get(details)===running)finish(details,open)}).catch(()=>{});
 }
 function enhance(root){
  if(root.nodeType!==1)return;
  if(root.matches('details'))prepare(root);
  root.querySelectorAll('details').forEach(prepare);
 }
 document.addEventListener('click',event=>{
  const summary=event.target.closest('summary');
  if(!summary||summary.parentElement.tagName!=='DETAILS'||event.defaultPrevented)return;
  if(event.target!==summary&&event.target.closest('a,button,input,select,textarea'))return;
  event.preventDefault();toggle(summary.parentElement,undefined,{animate:event.detail!==0});
 });
 window.fleetMotion={toggle,settle};
 let route=null;
 const observer=new MutationObserver(records=>{
  for(const record of records)for(const node of record.addedNodes)enhance(node);
  const content=document.getElementById('content');
  if(content&&content.children.length&&route!==location.pathname){route=location.pathname;content.classList.add('page-enter')}
 });
 observer.observe(document.getElementById('app'),{childList:true,subtree:true});
 observer.observe(document.getElementById('dialog'),{childList:true,subtree:true});
 enhance(document.getElementById('app'));
 document.addEventListener('animationend',event=>{if(event.animationName==='content-in')event.target.classList.remove('page-enter')});
 media.addEventListener('change',()=>{
  if(media.matches)document.querySelectorAll('details.is-disclosing').forEach(d=>finish(d,active.get(d)?.open??d.open));
 });

 // These existing entry points are shared by every form and data drawer.
 const surfaces=new WeakMap();
 animateSurface=function(el){
  surfaces.get(el)?.cancel();
  if(media.matches)return;
  const motion=el.animate([{opacity:0,transform:'translateX(24px)'},{opacity:1,transform:'translateX(0)'}],{duration:240,easing:ease});
  surfaces.set(el,motion);
 };
 closeModal=async function(){
  const dialog=document.getElementById('dialog');if(!dialog.open||dialog.dataset.closing)return;
  dialog.dataset.closing='true';
  const current=getComputedStyle(dialog),opacity=current.opacity,transform=current.transform;
  surfaces.get(dialog)?.cancel();
  let motion;
  try{
   if(!media.matches){
    motion=dialog.animate([{opacity,transform},{opacity:0,transform:'translateX(24px)'}],{duration:180,easing:ease,fill:'forwards'});
    surfaces.set(dialog,motion);await motion.finished;
   }
   dialog.close();
  }catch(error){if(error.name!=='AbortError')throw error}
  finally{if(surfaces.get(dialog)===motion){motion?.cancel();surfaces.delete(dialog)}delete dialog.dataset.closing}
 };
 // The old indicator was still calculated, but its CSS had been set to display:none.
 window.removeEventListener('resize',positionMonthPill);
 positionMonthPill=function(){
  const box=document.querySelector('.months');if(!box)return;
  let pill=box.querySelector('.month-pill');
  if(!pill){pill=document.createElement('i');pill.className='month-pill';pill.setAttribute('aria-hidden','true');box.prepend(pill)}
  const selected=box.querySelector('.selected');box.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===selected)));
  if(!selected){pill.style.opacity=0;return}
  const previous=pill.getBoundingClientRect();pill.getAnimations().forEach(a=>a.cancel());
  pill.style.cssText=`left:${selected.offsetLeft}px;top:${selected.offsetTop}px;width:${selected.offsetWidth}px;height:${selected.offsetHeight}px;opacity:1`;
  if(previous.width&&!media.matches){const next=pill.getBoundingClientRect();pill.animate([{transform:`translate(${previous.x-next.x}px,${previous.y-next.y}px) scaleX(${previous.width/next.width})`},{transform:'translate(0,0) scaleX(1)'}],{duration:220,easing:ease})}
 };
 window.addEventListener('resize',()=>positionMonthPill());
})();
