/* Server-driven provider refresh, with a protected, non-destructive view refresh. */
(() => {
 let state=null, polling=false, finished=null, baselineInitialized=false, viewPending=false, viewBusy=false;
 const dirtyForms=new Set();
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
  const failed=Object.values(state?.sources||{}).filter(s=>['error','busy'].includes(s.status));
  const label=running?'Обновление источников…':failed.length?'Требуют внимания: '+failed.map(s=>s.name).join(', '):state?.status==='interrupted'?'Обновление было прервано':state?.server_scheduler===false?'Автообновление сервера не запущено':'Автообновление каждые 5 минут';
  const details=Object.values(state?.sources||{}).map(s=>`<li><strong>${esc(s.name)}</strong> · ${labels[s.status]||esc(s.status)}<br><span>${esc(s.message||'')}</span><br><small>Последний успех: ${esc(stamp(s.last_success_at))}</small></li>`).join('');
  return `<div class="refresh-overview"><div><span class="refresh-status" role="status">${esc(label)}</span><small>Проверено: ${esc(stamp(state?.last_finished_at))}${viewPending?' · Новые данные появятся после завершения ввода.':''}</small></div><button type="button" class="refresh-trigger" ${running?'disabled':''}>${running?'Обновляется…':'Обновить данные'}</button></div><details class="refresh-details"><summary>Период и состояние обновления</summary><p>Автоматически: текущий месяц по МСК. Спутниковая история: последние завершённые сутки. Кнопка: ${esc(periodLabel())}.</p><p>Excel обновляется отдельно при загрузке файлов. ${U.role==='admin'?'Обновление получает данные из подключённых источников.':'Кнопка перечитывает рабочую базу. Источники автоматически обновляет сервер; запуск вручную доступен руководителю.'}</p>${state?.next_run_at?`<p>Следующий запуск: ${esc(stamp(state.next_run_at))}.</p>`:''}${state?.message?`<p>${esc(state.message)}</p>`:''}${details?`<ul class="refresh-sources">${details}</ul>`:''}</details>`;
 }
 function mount(){
  if(!U)return;
  const header=document.querySelector('#main > header');if(!header)return;
  let bar=document.getElementById('data-refresh');
  if(!bar){bar=document.createElement('section');bar.id='data-refresh';bar.className='refresh-bar';bar.setAttribute('aria-label','Обновление данных');header.insertAdjacentElement('afterend',bar)}
  const html=markup();if(bar.dataset.markup===html)return;
  // Polling must not remove a focused button or an expanded disclosure.
  const opened=bar.querySelector('details')?.open;
  const focused=bar.contains(document.activeElement)?document.activeElement.tagName==='SUMMARY'?'summary':document.activeElement.className:null;
  bar.innerHTML=html;bar.dataset.markup=html;
  if(opened)bar.querySelector('details').open=true;
  const button=bar.querySelector('button');button.onclick=manual;
  if(focused==='refresh-trigger'&&!button.disabled)button.focus({preventScroll:true});
  if(focused==='summary')bar.querySelector('summary').focus({preventScroll:true});
 }
 function inputBusy(){
  for(const form of dirtyForms)if(!form.isConnected)dirtyForms.delete(form);
  return document.querySelector('dialog[open]')||document.activeElement?.matches('input,textarea,select,[contenteditable="true"]')||dirtyForms.size;
 }
 async function updateView(){
  if(!U||!viewPending||viewBusy||inputBusy())return;
  viewBusy=true;
  const searches=[...document.querySelectorAll('.table-search input')].map(e=>e.value);
  const tables=[...document.querySelectorAll('#content .table-wrap')].map(w=>({left:w.scrollLeft,sort:[...w.querySelectorAll('th')].map(h=>h.getAttribute('aria-sort')).findIndex(v=>v==='ascending'||v==='descending'),direction:w.querySelector('th[aria-sort=ascending],th[aria-sort=descending]')?.getAttribute('aria-sort')}));
  const route=location.pathname;
  try{
   const data=await api('data');
   if(inputBusy()||route!==location.pathname)return;
   D=data;viewPending=false;
   await render();
   if(route!==location.pathname)return;
   enhanceTables();
   document.querySelectorAll('#content .table-wrap').forEach((w,i)=>{const saved=tables[i];if(!saved)return;w.scrollLeft=saved.left;if(saved.sort>=0){const button=w.querySelectorAll('th')[saved.sort]?.querySelector('.sort');button?.click();if(saved.direction==='descending')button?.click()}});
   document.querySelectorAll('.table-search input').forEach((e,i)=>{if(searches[i]){e.value=searches[i];e.dispatchEvent(new Event('input',{bubbles:true}))}});
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
