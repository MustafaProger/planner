/* Server-driven provider refresh, with a protected, non-destructive view refresh. */
(() => {
 let state=null, polling=false, finished=null, baselineInitialized=false, viewPending=false, viewBusy=false, refreshBar=null;
 const dirtyForms=new Set();
 const renderedMarkup=new WeakMap();
 function setMarkup(node,value){
  if(renderedMarkup.get(node)===value)return;
  renderedMarkup.set(node,value);node.innerHTML=value;
 }
 const stamp=value=>value?new Date(value).toLocaleString('ru-RU',{timeZone:'Europe/Moscow',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})+' МСК':'ещё не выполнялось';
 const labels={pending:'Ожидает',running:'Обновляется',success:'Обновлено',error:'Ошибка',busy:'Уже обновляется',unconfigured:'Не подключён'};
 const periodLabel=()=>{
  if(['neftmdata','rosneftdata'].includes(tab)){const period=fuelPeriods[tab.replace('data','')];return period.from+' — '+period.to}
  if(['planner','calendar'].includes(tab))return calMonth;
  if(document.querySelector('#filters #from'))return from+' — '+to;
  return 'текущий месяц';
 };
 function markup(){
  const running=state?.status==='running';
  const incidents=state?.alerts?.incidents||[];
  const failed=Object.values(state?.sources||{}).filter(s=>['error','busy'].includes(s.status));
  const label=incidents.length?'Обновление требует внимания':running?'Обновление источников…':failed.length?'Требуют внимания: '+failed.map(s=>s.name).join(', '):state?.status==='interrupted'?'Обновление было прервано':state?.server_scheduler===false?'Автообновление сервера не запущено':'Автообновление каждые 5 минут';
  const details=Object.values(state?.sources||{}).map(s=>`<li><strong>${esc(s.name)}</strong> · ${labels[s.status]||esc(s.status)}<br><span>${esc(s.message||'')}</span>${s.catchup?.pending_days?`<br><span>Догружаются пропущенные дни: ${esc(s.catchup.pending_days)}${s.catchup.from?' · начиная с '+esc(s.catchup.from):''}.</span>`:''}<br><small>Последний успех: ${esc(stamp(s.last_success_at))}</small></li>`).join('');
  return {running,label,alerts:incidents.map(x=>`<p><strong>${esc(x.title||'Обновление требует внимания')}</strong> ${esc(x.message)}</p>`).join(''),checked:`Проверено: ${stamp(state?.last_finished_at)}${viewPending?' · Новые данные появятся после завершения ввода.':''}`,body:`<p>Автоматически: ${esc(state?.automatic_scope||'текущий месяц по МСК; история спутника — последние завершённые сутки.')} Кнопка: ${esc(periodLabel())}.</p><p>Excel обновляется отдельно при загрузке файлов. ${U.role==='admin'?'Обновление получает данные из подключённых источников.':'Кнопка перечитывает рабочую базу. Источники автоматически обновляет сервер; запуск вручную доступен руководителю.'}</p>${state?.next_run_at?`<p>Следующий запуск: ${esc(stamp(state.next_run_at))}.</p>`:''}${state?.message?`<p>${esc(state.message)}</p>`:''}${details?`<ul class="refresh-sources">${details}</ul>`:''}${state?.alerts?.delivery?.configured?'':'<p class="muted">Предупреждения отображаются в приложении. Внешние уведомления не настроены.</p>'}${state?.alerts?.delivery?.error?`<p>${esc(state.alerts.delivery.error)}</p>`:''}${state?.alerts?.recent?.length?`<details><summary>История предупреждений</summary>${state.alerts.recent.slice(0,3).map(x=>`<p>${esc(x.title)} · ${x.status==='resolved'?'восстановлено':'закрыто'} · ${esc(stamp(x.resolved_at))}</p>`).join('')}</details>`:''}`};
 }
 function mount(){
  if(!U)return;
  const header=document.querySelector('#main > header');if(!header)return;
  let bar=document.getElementById('data-refresh');
  if(!bar){
   // Reuse the disclosure on navigation / data refresh, including its expanded state.
   bar=refreshBar;
   if(!bar){
    bar=document.createElement('section');bar.id='data-refresh';bar.className='refresh-bar';bar.setAttribute('aria-label','Обновление данных');
    bar.innerHTML='<div class="refresh-overview"><div><span class="refresh-status" role="status"></span><small class="refresh-checked"></small></div><button type="button" class="refresh-trigger">Обновить данные</button></div><div class="refresh-alerts" role="alert"></div><details class="refresh-details"><summary>Период и состояние обновления</summary><div class="refresh-details-body"></div></details>';
    bar.querySelector('button').onclick=manual;
   }
   (document.getElementById('page-help')||header).insertAdjacentElement('afterend',bar);refreshBar=bar;
  }
  const view=markup(),button=bar.querySelector('button');
  const setText=(selector,value)=>{const node=bar.querySelector(selector);if(node.textContent!==value)node.textContent=value};
  setText('.refresh-status',view.label);setText('.refresh-checked',view.checked);
  const alerts=bar.querySelector('.refresh-alerts');
  if(alerts)setMarkup(alerts,view.alerts);
  const buttonText=view.running?'Обновляется…':'Обновить данные';
  if(button.textContent!==buttonText)button.textContent=buttonText;
  button.disabled=view.running;
  // Only the contents change. Polling must never recreate a summary or interrupt a toggle.
  const body=bar.querySelector('.refresh-details-body');
  // Compare source markup: motion enhancements change the live DOM.
  setMarkup(body,view.body);
 }
 function disclosureStates(){
  const seen=new Map();
  return [...document.querySelectorAll('#main details')].map(node=>{
   const label=node.id||node.querySelector('summary')?.textContent||'',index=seen.get(label)||0;seen.set(label,index+1);
   return {key:label+':'+index,open:node.dataset.motionExpanded?node.dataset.motionExpanded==='true':node.open};
  });
 }
 function restoreDisclosures(saved){
  const seen=new Map(),states=new Map(saved.map(item=>[item.key,item.open]));
  document.querySelectorAll('#main details').forEach(node=>{
   const label=node.id||node.querySelector('summary')?.textContent||'',index=seen.get(label)||0;seen.set(label,index+1);
   const open=states.get(label+':'+index);if(open===undefined)return;
   if(window.fleetMotion)window.fleetMotion.settle(node,open);else node.open=open;
  });
 }

 function inputBusy(){
  for(const form of dirtyForms)if(!form.isConnected)dirtyForms.delete(form);
  return document.querySelector('dialog[open]')||document.activeElement?.matches('input,textarea,select,[contenteditable="true"]')||dirtyForms.size;
 }
 async function updateView(){
  if(!U||!viewPending||viewBusy||inputBusy())return;
  viewBusy=true;
  const route=location.pathname;
  try{
   const data=await api('data');
   if(inputBusy()||route!==location.pathname)return;
   // Capture the latest interaction after the request: the user may have scrolled
   // or toggled a disclosure while data was in flight.
   const searches=[...document.querySelectorAll('.table-search input')].map(e=>e.value);
   const tables=[...document.querySelectorAll('#content .table-wrap')].map(w=>({left:w.scrollLeft,sort:[...w.querySelectorAll('th')].map(h=>h.getAttribute('aria-sort')).findIndex(v=>v==='ascending'||v==='descending'),direction:w.querySelector('th[aria-sort=ascending],th[aria-sort=descending]')?.getAttribute('aria-sort')}));
   const expanded=disclosureStates(),position={left:window.scrollX,top:window.scrollY};
   D=data;viewPending=false;
   await render();
   if(route!==location.pathname)return;
   restoreDisclosures(expanded);
   enhanceTables();
   document.querySelectorAll('#content .table-wrap').forEach((w,i)=>{const saved=tables[i];if(!saved)return;w.scrollLeft=saved.left;if(saved.sort>=0){const button=w.querySelectorAll('th')[saved.sort]?.querySelector('.sort');button?.click();if(saved.direction==='descending')button?.click()}});
   document.querySelectorAll('.table-search input').forEach((e,i)=>{if(searches[i]){e.value=searches[i];e.dispatchEvent(new Event('input',{bubbles:true}))}});
   window.scrollTo(position);
  }catch(error){viewPending=true;toast(error.message)}
  finally{viewBusy=false;mount()}
 }
 async function poll(){
  if(!U||polling)return;polling=true;
  try{
   state=await api('refresh');
   const nextFinished=state.last_finished_at||null;
   if(baselineInitialized&&nextFinished&&finished!==nextFinished)viewPending=true;
   finished=nextFinished;baselineInitialized=true;
   mount();await updateView();
  }catch(error){const bar=document.getElementById('data-refresh');if(bar)bar.querySelector('.refresh-status').textContent='Не удалось проверить обновление. Повторим автоматически.'}
  finally{polling=false}
 }
 async function manual(){
  const button=document.querySelector('.refresh-trigger');if(button)button.disabled=true;
  try{
   if(U.role==='admin'){
    let body={};
    if(['neftmdata','rosneftdata'].includes(tab)){
     body={...fuelPeriods[tab.replace('data','')]};
    }else if(['calendar','planner'].includes(tab)){
     const [year,month]=calMonth.split('-').map(Number);
     body={from:calMonth+'-01',to:calMonth+'-'+new Date(year,month,0).getDate()};
    }else if(document.querySelector('#filters #from'))body={from,to};
    state=await api('refresh',{method:'POST',body:JSON.stringify(body)});
    toast(state.accepted?'Обновление источников запущено. Можно продолжать работу.':'Обновление уже выполняется.');
   }else{viewPending=true;await updateView();toast(viewPending?'Данные обновятся после завершения ввода.':'Рабочая база обновлена.')}
  }catch(error){toast(error.message)}
  finally{if(button?.isConnected)button.disabled=false;mount()}
 }
 document.addEventListener('input',event=>{
  const form=event.target.closest('form');
  if(form&&!form.closest('#data-refresh')&&event.target.type!=='search')dirtyForms.add(form);
 });
 document.addEventListener('change',event=>{const form=event.target.closest('form');if(form&&!form.closest('#data-refresh'))dirtyForms.add(form)});
 // Keep failed submissions protected. A successful render removes the old form,
 // and inputBusy then discards its disconnected dirty marker.
 document.addEventListener('focusout',()=>setTimeout(updateView,0));
 document.addEventListener('close',()=>setTimeout(updateView,0),true);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden){poll();updateView()}});
 new MutationObserver(mount).observe(document.getElementById('app'),{childList:true,subtree:true});
 setInterval(()=>{if(!document.hidden)poll()},10000);
 setInterval(()=>{if(U){viewPending=true;updateView()}},300000);
 window.fleetRefresh={poll,updateView};
 boot().then(poll).catch(error=>toast(error.message));
})();
