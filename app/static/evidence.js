/* Source-confirmed mileage and responsibility intervals. No inferred business facts. */
async function evidenceUpload(path,body){
 const response=await fetch('/api/evidence/mileage/'+path,{method:'POST',headers:{'X-CSRF-Token':csrf},body});
 const result=await response.json();if(!response.ok)throw new Error(result.error||'Не удалось обработать отчет');return result;
}
let evidencePageRequest=0;
async function evidencePage(){
 const requestId=++evidencePageRequest,periodFrom=from,periodTo=to,navigationVersion=typeof renderVersion==='undefined'?null:renderVersion;
 const target=$('#content'),state=await api('evidence?'+new URLSearchParams({from:periodFrom,to:periodTo}));if(requestId!==evidencePageRequest||target!==$('#content')||tab!=='evidence'||from!==periodFrom||to!==periodTo||(navigationVersion!==null&&navigationVersion!==renderVersion))return;
 const boundaryStart=new Date(from+'T00:00:00+03:00'),boundaryEnd=new Date(to+'T00:00:00+03:00');boundaryEnd.setTime(boundaryEnd.getTime()+86400000);
 const rows=state.shifts.filter(r=>new Date(r.start)<boundaryEnd&&new Date(r.end)>boundaryStart);
 const names=Object.fromEntries(D.directories.drivers.map(r=>[r.id,r.name]));
 const mileageRows=D.trips.filter(r=>r.date>=periodFrom&&r.date<=periodTo&&r.km_observation);
 target.innerHTML=`<p class="note">Километраж принимается из свежего отчета ТТ после проверки ID, даты и автомобиля. Автоматическая выгрузка КМ из установленной версии ТТ пока не подключена. Смены — подтвержденные интервалы ответственности; часы заявок и моточасы считаются отдельно.</p><section class="panel"><div class="panel-head"><h2>Километраж ТТ</h2>${U.role==='admin'?'<button id="mileageUpload">Проверить отчет CSV / XLSX</button>':''}</div>${table(['API ID','Номер','Км','Дата источника','Основание','Состояние'],mileageRows.map(r=>[esc(r.provider_id),esc(r.number),fmt(r.km),esc(r.km_observation.source_as_of),esc(r.km_observation.source_ref),r.km_observation.status==='verified'?'Подтверждено':esc(r.km_observation.reason)]))}</section><section class="panel"><div class="panel-head"><h2>Фактические интервалы</h2>${U.role==='admin'?'<button id="shiftAdd">+ Подтвержденный интервал</button>':''}</div><p>Границы вводятся со смещением часового пояса. Пересечения требуют проверки и исключены из распределения спутниковых измерений. Оплачиваемые часы и перерывы здесь не определяются.</p>${table(['Водитель','Автомобиль','Начало','Конец','Длительность, ч','Основание','Состояние',''],rows.map(r=>[esc(r.driver),esc(r.vehicle),esc(r.start),esc(r.end),fmt(r.hours),esc(r.source_ref),r.status==='conflict'?'Пересечение: требуется проверка':'Подтверждено',U.role==='admin'?`<button data-edit-shift="${esc(r.id)}">Изменить</button> <button data-delete-shift="${esc(r.id)}">Удалить</button>`:'']))}</section><section class="panel"><h2>Распределение спутниковых измерений</h2><p>Каждый суточный интервал относится водителю только при единственной подтвержденной смене, покрывающей сутки целиком. Части суток не делятся пропорционально часам. Остальное остается на автомобиле. «—» означает отсутствие пригодных измерений, а не нулевую работу.</p>${table(['Показатель','Всего измерено','Распределено','Не распределено'],Object.entries(state.allocation.totals).map(([k,v])=>[esc({km:'Км',engine_hours:'Моточасы',movement_hours:'Движение, ч',fuel_liters:'Топливо, л'}[k]),fmt(v.available),fmt(v.assigned),fmt(v.unassigned)]))}<details><summary>Измерения и причины</summary>${table(['Автомобиль','Дата','Км','Моточасы','Водитель','Причина'],state.allocation.measurements.map(r=>[esc(r.vehicle),esc(r.date),fmt(r.km),fmt(r.engine_hours),esc(names[r.driver_id]||'Не распределено'),esc(r.reason)]))}</details></section>`;
 if($('#mileageUpload'))$('#mileageUpload').onclick=mileageForm;
 if($('#shiftAdd'))$('#shiftAdd').onclick=()=>shiftForm();
 target.querySelectorAll('[data-edit-shift]').forEach(b=>b.onclick=()=>shiftForm(rows.find(r=>r.id===b.dataset.editShift)));
 target.querySelectorAll('[data-delete-shift]').forEach(b=>b.onclick=async()=>{const row=rows.find(r=>r.id===b.dataset.deleteShift);if(!confirm('Удалить подтвержденный интервал? История сохранится.'))return;try{await api('evidence/shifts/'+row.id,{method:'DELETE',body:JSON.stringify({revision:row.revision})});await evidencePage()}catch(e){toast(e.message)}});
}
function mileageForm(){
 modal(`<h2>Проверить километраж из отчета ТТ</h2><p>CSV UTF-8 или первый лист XLSX. Заголовки: provider_id (постоянный API ID) или number (номер), date (ГГГГ-ММ-ДД), vehicle, km. Единицы — километры; пустое поле не равно нулю. Номер без ID сопоставляется только по единственному совпадению даты и машины.</p><form id="mileageForm" class="grid"><label>Отчет<input type="file" name="file" accept=".csv,.xlsx" required></label>${field('Дата формирования источником, с часовым поясом','source_as_of','','text','required placeholder="2026-11-02T11:00:00+03:00"')}${field('Отчет / документ ТТ и основание проверки','source_ref','','text','required maxlength="500"')}<button type="submit">Предварительная проверка</button></form><div id="mileagePreview" role="status"></div>`);
 const form=$('#mileageForm'),preview=$('#mileagePreview'),dialog=$('#dialog'),button=form.querySelector('button');
 let generation=0,committing=false;
 const sameForm=()=>form.isConnected&&$('#mileageForm')===form&&$('#dialog')===dialog;
 const active=()=>sameForm()&&dialog.open&&!dialog.dataset.closing;
 const current=id=>active()&&id===generation;
 form.oninput=()=>{
  if(!active()||committing)return;
  generation++;button.disabled=false;preview.textContent='Параметры изменились. Выполните проверку заново.';
 };
 form.onsubmit=async e=>{
  e.preventDefault();if(!active()||committing)return;
  const requestId=++generation,entries=Array.from(new FormData(form).entries());
  const upload=()=>{const body=new FormData();for(const [key,value] of entries)body.append(key,value);return body};
  button.disabled=true;preview.textContent='Проверяем отчет…';
  try{
   const result=await evidenceUpload('preview',upload());if(!current(requestId))return;
   const labels={ready:'Готово',unchanged:'Без изменений',older:'Более старый источник',invalid:'Ошибка',conflict:'Конфликт'};
   preview.innerHTML=`${table(['Строка','API ID','Км','Результат','Причина'],result.rows.map(r=>[fmt(r.row),esc(r.provider_id),fmt(r.km),esc(labels[r.status]),esc(r.reason)]))}<p>Будет добавлено: ${fmt(result.ready)}. Неизменившиеся и старые строки пропускаются. Любая ошибка или конфликт блокирует весь пакет.</p>${result.ready&&!result.rows.some(r=>['invalid','conflict'].includes(r.status))?'<label><input type="checkbox" id="mileageConfirmed"> Проверено: это сохраненный в ТТ километраж, дата источника и соответствия верны</label><button id="mileageCommit">Принять проверенные строки</button>':''}`;
   const commit=preview.querySelector('#mileageCommit'),confirmed=preview.querySelector('#mileageConfirmed');
   if(commit)commit.onclick=async()=>{
    if(!current(requestId)||committing)return;
    if(!confirmed.checked){toast('Подтвердите источник и соответствия.');return}
    committing=true;commit.disabled=true;
    const controls=Array.from(form.querySelectorAll('input,select,textarea,button')).map(node=>[node,node.disabled]);
    controls.forEach(([node])=>{node.disabled=true});
    try{
     const body=upload();body.set('token',result.token);body.set('confirmed','true');
     const saved=await evidenceUpload('confirm',body);if(!current(requestId))return;
     await closeModal();if(!sameForm()||dialog.open)return;
     await refresh();if(sameForm()&&!dialog.open)toast('Километраж сохранен: '+saved.applied);
    }catch(x){if(current(requestId))toast(x.message)}
    finally{
     committing=false;
     if(current(requestId)){commit.disabled=false;controls.forEach(([node,disabled])=>{node.disabled=disabled})}
    }
   };
  }catch(x){if(current(requestId))preview.textContent=x.message}
  finally{if(current(requestId))button.disabled=false}
 };

}
function shiftForm(r={}){
 modal(`<h2>${r.id?'Изменить':'Подтвердить'} фактический интервал</h2><p>Используйте табель или журнал ответственного. Начало и конец заявки сами по себе не подтверждают смену.</p><form id="shiftForm" class="grid">${selectField('Водитель','driver_id',directoryOptions('drivers',r.driver_id))}${selectField('Автомобиль','vehicle_id',directoryOptions('vehicles',r.vehicle_id))}${field('Начало с часовым поясом','start',r.start||from+'T08:00:00+03:00','text','required')}${field('Конец с часовым поясом','end',r.end||from+'T20:00:00+03:00','text','required')}${field('Источник / документ / строка','source_ref',r.source_ref,'text','required maxlength="500"')}${check('Фактический интервал проверен по указанному источнику','confirmed',false)}${formFooter()}</form>`);
 submitHandler($('#shiftForm'),b=>writeWorkspace('evidence/shifts'+(r.id?'/'+r.id:''),{...b,revision:r.revision},r.id?'PUT':'POST'));
}
