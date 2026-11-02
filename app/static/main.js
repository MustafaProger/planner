const $=s=>document.querySelector(s),esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),fmt=x=>x==null?'—':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(x),money=x=>fmt(x)+' ₽';
let statisticsView='totals',attributeFilters={vehicle_brand:'',vehicle_company:'',driver_company:'',resource_type:''};
let planView='list';let D,U,csrf,tab='statistics',group='vehicle',from='2026-08-01',to='2026-08-31',car='',driver='',client='',type='',calMode='vehicle',calMonth='2026-08',calendarFocusDay='',reportRows=[];
const tabs={dashboard:'Обзор сверки',statistics:'Статистика',calendar:'Календарь',planner:'Планировщик',comparison:'План–факт',reconcile:'Сверка со спутником',orders:'Заявки ТрансТрейд',neftm:'Нефтьмагистраль',monitoring:'Мониторинг · ГЛОНАССсофт',rosneft:'Роснефть',transtrade:'ТрансТрейд',directories:'Справочники',connections:'Источники данных',users:'Доступы и журнал'};
const navTabs={...tabs,monitoring:'ГЛОНАССсофт'};
function pagePath(key){const section=Object.keys(sections).find(s=>sections[s].includes(key))||'integrations';return '/'+section+'/'+key}
function pageFromURL(){const key=location.pathname.split('/').filter(Boolean).pop();return Object.hasOwn(tabs,key)?key:'statistics'}
let dashboardReturnFilters=null;
function filterState(){return {from,to,car,driver,client,type,group,attributeFilters:{...attributeFilters},statisticsView,comparisonMetrics:typeof comparisonMetrics==='undefined'?'money':comparisonMetrics,workspaceGroup:typeof workspaceGroup==='undefined'?'vehicle':workspaceGroup,calMonth,calMode,calendarFocusDay,planView,planRows:typeof planRows==='undefined'?'route':planRows}}
function restoreFilters(state){if(state){({from,to,car,driver,client,type,group}=state);attributeFilters={vehicle_brand:'',vehicle_company:'',driver_company:'',resource_type:'',...state.attributeFilters};statisticsView=state.statisticsView||'totals';if(typeof comparisonMetrics!=='undefined')comparisonMetrics=state.comparisonMetrics||'money';if(typeof workspaceGroup!=='undefined')workspaceGroup=state.workspaceGroup||'vehicle';calMonth=state.calMonth||calMonth;calMode=state.calMode||'vehicle';calendarFocusDay=state.calendarFocusDay||'';planView=state.planView||'list';if(typeof planRows!=='undefined')planRows=state.planRows||'route'}}
function saveNavigationState(){history.replaceState({...history.state,filters:filterState()},'')}
function navigate(key,{preserveFilters=false,filters=null}={}){
 if(typeof dismissReportDetails==='function')dismissReportDetails();
 if(key==='users'&&U.role!=='admin')key='statistics';
 if(tab!==key){
  saveNavigationState();
  if(tab==='dashboard'&&filters)dashboardReturnFilters=filterState();
  if(!preserveFilters){car=driver=client=type='';Object.keys(attributeFilters).forEach(k=>attributeFilters[k]='')}
  if(key==='dashboard'&&dashboardReturnFilters)restoreFilters(dashboardReturnFilters);
  if(filters)restoreFilters({...filterState(),...filters});
  history.pushState({filters:filterState()},'',pagePath(key));
 }
 tab=key;render({preserveScroll:false});window.scrollTo({top:0,behavior:'instant'});$('.sidebar')?.classList.remove('is-open');
}
window.addEventListener('popstate',event=>{if(U){if(typeof dismissReportDetails==='function')dismissReportDetails();restoreFilters(event.state?.filters);tab=pageFromURL();if(tab==='users'&&U.role!=='admin')tab='statistics';render({preserveScroll:false});window.scrollTo({top:0,behavior:'instant'})}});
async function api(url,opt={}){const r=await fetch('/api/'+url,{...opt,headers:{...(opt.body instanceof FormData?{}:{'Content-Type':'application/json'}),'X-CSRF-Token':csrf||'',...opt.headers}});let b;try{b=await r.json()}catch{throw Error('Ошибка сервера: '+r.status)}if(!r.ok){const error=Error(b.error||'Недостаточно прав или ошибка запроса');error.status=r.status;throw error}return b}
function toast(t){$('#toast').textContent=t;$('#toast').style.display='block';setTimeout(()=>$('#toast').style.display='none',6000)}
function table(headers,rows,click=false,searchable=true){return `<div class="table-wrap"${searchable?'':' data-no-search'}><table><thead><tr>${headers.map(h=>`<th scope="col" aria-sort="none"><button class="sort" type="button">${esc(h)}<span aria-hidden="true"> ↕</span></button></th>`).join('')}</tr></thead><tbody>${rows.map((r,i)=>`<tr ${click?`class="clickable" tabindex="0" aria-label="Открыть детализацию" data-row="${i}"`:''}>${r.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>${rows.length?'':'<div class="empty">Нет данных за выбранный период</div>'}</div>`}
function options(items,value='',empty='Все'){return (empty!==null?`<option value="">${esc(empty)}</option>`:'')+items.map(x=>`<option value="${esc(x)}" ${x===value?'selected':''}>${esc(x)}</option>`).join('')}
function within(r){return r.date>=from&&r.date<=to&&(!car||r.vehicle===car)&&(!driver||r.driver===driver)&&(!client||r.client===client)&&(!type||r.type===type)}
function param(){return new URLSearchParams({from,to,vehicle:car,driver,client,type,group,...(tab==='statistics'?attributeFilters:{})})}
function reportFilterFields(page){return `<label>С<input id="from" type="date" value="${from}"></label><label>По<input id="to" type="date" value="${to}"></label>${page==='evidence'?'':`<label>Автомобиль<select id="car">${options(vehicleNames(),car)}</select></label>`}${['dashboard','reconcile','economics','telemetry','evidence'].includes(page)?'':`<label>Водитель<select id="driver">${options(Object.keys(D.drivers).sort(),driver)}</select></label>`}${['statistics','orders'].includes(page)?`<label>Клиент<select id="client">${options([...new Set(D.trips.map(r=>r.client))].sort(),client)}</select></label><label>Тип транспорта<select id="type">${options([...new Set(D.trips.map(r=>r.type))].sort(),type)}</select></label>`:''}`}

function modal(html){const d=$('#dialog');d.innerHTML='<button type="button" class="dialog-close" data-close aria-label="Закрыть карточку">×</button>'+html;d.classList.toggle('detail-drawer',!d.querySelector('form'));d.showModal();d.setAttribute('aria-label',d.querySelector('h2')?.textContent||'Подробности');animateSurface(d);d.querySelectorAll('[data-close]').forEach(b=>b.onclick=closeModal);d.oncancel=e=>{e.preventDefault();closeModal()}}
function metrics(items){return `<div class="metrics">${items.map(([a,b,c])=>`<div class="metric"><span class="muted">${a}</span><b>${b}</b><small>${c||''}</small></div>`).join('')}</div>`}
function bars(rows,key='revenue'){let max=Math.max(1,...rows.map(r=>Math.abs(r[key]||0)));return rows.slice(0,8).map(r=>`<div class="barrow"><span title="${esc(r.name)}">${esc(r.name)}</span><div class="bar"><i style="width:${Math.max(0,(r[key]||0)/max*100)}%"></i></div><span>${fmt(r[key])}</span></div>`).join('')||'<p class="muted">Нет данных</p>'}
const sections={analytics:['dashboard','statistics','comparison','reconcile'],planning:['calendar','planner'],data:['orders','directories','connections','users'],integrations:['neftm','monitoring','rosneft','transtrade']};
const sectionNames={analytics:'Аналитика',planning:'Планирование',data:'Данные',integrations:'Подключения'};
function shell(){const oldMonths=$('.months');const oldSidebar=$('.sidebar');const sidebarScroll=oldSidebar?{outer:oldSidebar.scrollTop,nav:oldSidebar.querySelector('nav').scrollTop}:null;const section=Object.keys(sections).find(k=>sections[k].includes(tab)); $('#app').innerHTML=`<header class="topbar"><a class="brand" href="/analytics/statistics" aria-label="Логистика — главная"><span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 17V7m7 10V4m7 13v-6M3 21h18"/></svg></span>Логистика</a><span class="header-context">Рабочее пространство <span> / ${sectionNames[section]}</span></span><button id="menu-toggle" aria-label="Открыть навигацию" aria-expanded="false" aria-controls="sidebar"><span class="menu-line menu-line-top" aria-hidden="true"></span><span class="menu-line menu-line-bottom" aria-hidden="true"></span></button></header><aside class="sidebar" id="sidebar"><nav aria-label="Разделы сервиса"><i class="nav-capsule" aria-hidden="true"></i>${Object.entries(sections).map(([section,items])=>`<div class="nav-group"><h2>${sectionNames[section]}</h2>${items.filter(k=>k!=='users'||U.role==='admin').map(k=>`<a href="${pagePath(k)}" data-tab="${k}" class="${k===tab?'active':''}" aria-current="${k===tab?'page':'false'}"><span class="nav-dot" aria-hidden="true"></span>${navTabs[k]}</a>`).join('')}</div>`).join('')}</nav><div class="sidebar-account"><div class="account"><svg class="account-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="8" r="3.5"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></svg><span>${esc(U.name)}</span><button id="logout" title="Выйти из аккаунта" aria-label="Выйти из аккаунта"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M9 4H5v16h4M13 7l5 5-5 5M9 12h10"/></svg></button></div></div></aside><main id="main"><header><div><h1>${tabs[tab]}</h1><span class="muted">Автопарк · работа, загрузка и экономика перевозок</span></div><span class="badge">${section==='integrations'?'Внешний источник':'Рабочая база · '+[...new Set(D.trips.map(r=>r.date.slice(0,7)))].sort().join(", ")}</span></header><div id="filters"></div><div id="content"></div></main>`;
 // Reattaching the sidebar can reset both desktop nav and mobile panel scroll.
 if(oldSidebar){$('.sidebar').replaceWith(oldSidebar);oldSidebar.scrollTop=sidebarScroll.outer;oldSidebar.querySelector('nav').scrollTop=sidebarScroll.nav}document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.tab===tab);b.setAttribute('aria-current',b.dataset.tab===tab?'page':'false')});positionCapsule();$('#menu-toggle').onclick=()=>{const opened=$('.sidebar').classList.toggle('is-open');$('#menu-toggle').setAttribute('aria-expanded',String(opened));$('#menu-toggle').setAttribute('aria-label',opened?'Закрыть навигацию':'Открыть навигацию');if(opened)positionCapsule()}; document.querySelector('.brand').onclick=e=>{e.preventDefault();navigate('statistics')};document.querySelectorAll('[data-section]').forEach(b=>b.onclick=()=>{car=driver=client=type='';tab=sections[b.dataset.section][0];render()});
 document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();navigate(b.dataset.tab)});$('#logout').onclick=async()=>{await api('logout',{method:'POST'});location.reload()};
 if(['dashboard','statistics','orders','comparison','reconcile','planreport','downtime','economics','telemetry','quality','evidence'].includes(tab)){$('#filters').innerHTML=`<form class="toolbar filters-form">${reportFilterFields(tab)}<div class="filter-actions"><button id="apply" type="submit" class="primary">Применить</button><button id="reset" type="button">Сбросить фильтры</button></div></form><div class="months">${[...new Set([...D.trips,...D.plans].map(r=>r.date.slice(0,7)))].sort().map((m,i)=>`<button data-month="${m}" class="${from===m+'-01'&&to===m+'-'+new Date(Number(m.slice(0,4)),Number(m.slice(5)),0).getDate()?'selected':''}">${new Date(m+'-15').toLocaleDateString('ru-RU',{month:'long',year:'numeric'})}</button>`).join('')}</div>`;
 if(oldMonths){$('.months').replaceWith(oldMonths);oldMonths.querySelectorAll('[data-month]').forEach(b=>b.classList.toggle('selected',from===b.dataset.month+'-01'&&to===b.dataset.month+'-'+new Date(+from.slice(0,4),+from.slice(5,7),0).getDate()))}positionMonthPill(); $('.filters-form').onsubmit=e=>{e.preventDefault();from=$('#from').value;to=$('#to').value;if(!from||!to||from>to)return toast('Проверьте период');car=$('#car')?.value||'';driver=$('#driver')?.value||'';client=$('#client')?.value||'';type=$('#type')?.value||'';render()};$('#reset').onclick=()=>{car=driver=client=type='';Object.keys(attributeFilters).forEach(k=>attributeFilters[k]='');render()};document.querySelectorAll('[data-month]').forEach(b=>b.onclick=()=>{from=b.dataset.month+'-01';to=b.dataset.month+'-'+new Date(Number(from.slice(0,4)),Number(from.slice(5,7)),0).getDate();render()});}
 if(['calendar','planner'].includes(tab)){$('#filters').innerHTML=`<form class="toolbar filters-form"><label>Автомобиль / ресурс<select id="car">${options(Object.keys(D.vehicles).sort(),car)}</select></label><label>Водитель<select id="driver">${options(Object.keys(D.drivers).sort(),driver)}</select></label><button class="primary">Применить</button><button id="reset" type="button">Сбросить фильтры</button></form>`;$('.filters-form').onsubmit=e=>{e.preventDefault();car=$('#car').value;driver=$('#driver').value;render()};$('#reset').onclick=()=>{car=driver='';render()};}
}
let renderedTab=null,renderVersion=0;
async function render({preserveScroll=true}={}){
 if(tab==='dashboard')dashboardReturnFilters=null;
 saveNavigationState();
 const version=++renderVersion,keepPosition=preserveScroll&&renderedTab===tab,position={left:window.scrollX,top:window.scrollY};
 const app=$('#app');
 // Keep the document tall while the shell and asynchronous results are replaced.
 if(keepPosition)app.style.minHeight=app.getBoundingClientRect().height+'px';
 else app.style.minHeight='';
 renderedTab=tab;document.title=tabs[tab]+' · Логистика';shell();const target=$('#content');
 target.innerHTML='<div class="empty" role="status">Загрузка данных…</div>';
 try{await ({dashboard,statistics,orders,calendar,planner,comparison,reconcile:reconciliation,planreport:()=>workspaceReport('plans'),downtime:()=>workspaceReport('downtime'),economics:()=>workspaceReport('economics'),telemetry,quality:qualityPage,coverage:()=>extraTable('coverage'),fuelcards:()=>extraTable('card_bindings'),expenses:()=>extraTable('expenses'),directories,connections,users,neftm:()=>integration('neftm'),monitoring:()=>integration('monitoring'),rosneft:()=>integration('rosneft'),transtrade:()=>integration('transtrade'),neftmdata:()=>sourceData('neftm'),rosneftdata:()=>sourceData('rosneft'),monitoringdata:()=>sourceData('monitoring'),excel:excelImport,guide:userGuide,evidence:()=>evidencePage()}[tab])()}
 catch(e){if(target!==$('#content'))return;target.innerHTML=`<div class="note">${esc(e.message)}</div>`}
 finally{if(version===renderVersion){app.style.minHeight='';if(keepPosition)window.scrollTo({...position,behavior:'instant'})}}
}
const attributeLabels={vehicle_brand:'Марка автомобиля',vehicle_company:'Принадлежность автомобиля',driver_company:'Компания водителя',resource_type:'Вид ресурса'};
const resourceLabels={vehicle:'Автомобиль',partner:'Партнёр',placeholder:'Служебное обозначение',service:'Дополнительные работы'};
const averageLabels={average_record_revenue:'Средняя сумма записи, ₽',average_record_payout:'Средняя выплата по записи, ₽',average_trip_revenue:'Средняя выручка рейса, ₽',average_trip_payout:'Средняя выплата рейса, ₽',average_km:'Средний пробег рейса ТТ, км',average_hours:'Средняя длительность заявки-рейса, ч',revenue_per_trip:'Вся выручка на рейс, ₽'};
function statisticsColumns(){return statisticsView==='averages'?[['name','Группа'],['records','Записи'],['trips','Рейсы'],...Object.entries(averageLabels)]:[['name','Группа'],['revenue','Выручка, ₽'],['payout','Исполнителям, ₽'],['payout_percent','Выплаты / выручка, %'],['balance','Разница, ₽'],['trips','Рейсы'],['days','Дни ТТ'],['sat_days','Дни с показаниями'],['hours','Часы заявок ТТ'],['sat_hours','Интервал Excel, ч'],['sat_engine_hours','Моточасы, ч'],['fuel_liters','Расход, л'],['fuel_days','Топливо, дней'],['fuel_l_per_100_km','л / 100 км'],['km','Км ТТ'],['sat_km','Км спутник'],['delta_km','Разница, км'],['average_hours','Час / рейс'],['rub_km','₽ / км ТТ'],['rub_hour','₽ / час ТТ'],['missing_trip_days','Нет пробега в дни рейсов'],['km_source','Источник пробега'],['engine_days','Моточасы, дней']]}
function statisticsCell(a,key){if(key==='name')return esc(group==='resource_type'?(resourceLabels[a[key]]||a[key]):a[key]);if(key==='km_source')return esc(a[key]);if(['fuel_days','engine_days'].includes(key))return `${fmt(a[key])} / ${fmt(a.period_days)}`;return fmt(a[key])}
async function statistics(){
 const target=$('#content'),r=await api('report?'+param()),t=r.totals;if(target!==$('#content'))return;reportRows=r.rows;
 const columns=statisticsColumns(),labels={vehicle:'Автомобили',driver:'Водители',pair:'Машина + водитель',client:'Клиенты',type:'Типы транспорта',carrier:'Исполнители заявки',date:'По дням',category:'Виды начислений',week:'По неделям (ISO)',logist:'Логисты',month:'По месяцам',quarter:'По кварталам',year:'По годам',payment:'Расчёт с клиентом',payout_method:'Расчёт с исполнителем',...attributeLabels};
 target.innerHTML=`${metrics([['Выручка по заявкам',money(t.revenue),'Исходные суммы ТрансТрейда'],['Исполнителям',money(t.payout),'Водители и подрядчики'],['Рейсы',fmt(t.trips||0),`${fmt(t.records||0)} записей с доплатами и удержаниями`],['Пробег рейсов ТТ',fmt(t.km)+' км',fmt(t.hours)+' часов по заявкам-рейсам']])}
 <details class="panel" ${Object.values(attributeFilters).some(Boolean)?'open':''}><summary>Марка и принадлежность · текущий справочник</summary><form id="attributeFilters" class="toolbar">${Object.entries(attributeLabels).map(([k,label])=>`<label>${label}<select name="${k}">${selectPairs((r.filter_options?.[k]||[]).map(v=>[v,k==='resource_type'?(resourceLabels[v]||v):v]),attributeFilters[k],'Все')}</select></label>`).join('')}<button class="primary">Применить</button></form><p class="muted">Принадлежность автомобиля, компания водителя и исполнитель заявки — отдельные поля. Эти фильтры и разрезы используют текущие справочники; историческая принадлежность на дату рейса не установлена. «Не указано» сохраняется отдельной группой.</p></details>
 <div class="panel"><div class="panel-head"><h2>Сводная таблица</h2><div><select id="group" aria-label="Группировка отчёта">${selectPairs(Object.entries(labels),group,null)}</select> <select id="statisticsView" aria-label="Показатели статистики">${selectPairs([['totals','Суммы и загрузка'],['averages','Средние показатели']],statisticsView,null)}</select> <button id="export">Скачать CSV</button></div></div>
 ${table(columns.map(c=>c[1]),r.rows.map(a=>columns.map(([k])=>statisticsCell(a,k))),true)}
 ${statisticsView==='averages'?`<h3>Итог всей выборки</h3>${table(columns.map(c=>c[1]),Object.keys(t).length?[columns.map(([k])=>statisticsCell(t,k))]:[])}<details><summary>Формулы средних</summary>${Object.entries(r.average_formulas||{}).map(([k,v])=>`<p><b>${esc(averageLabels[k])}</b>: ${esc(v)}.</p>`).join('')}<p>Итог считается из исходных сумм и количества записей, а не как среднее средних групп. Доплаты и удержания входят в среднюю сумму записи и всю выручку на рейс, но исключены из среднего дохода/выплаты самого рейса. При неизвестной сумме или пробеге основное среднее не рассчитывается; нулевой знаменатель даёт «—». Часы заявки не равны фактической смене.</p></details>`:''}
 <p class="muted">Нажмите строку для исходных записей. Разница = выручка − выплаты; это не чистая прибыль. Дни, часы и километры считаются только по рейсам; доплаты и удержания не увеличивают загрузку.</p></div>
 <div class="split"><div class="panel"><h2>Выручка по выбранной группировке</h2>${bars(r.rows)}</div><div class="panel"><h2>Пробег по заявкам</h2>${bars([...r.rows].sort((a,b)=>(b.km||0)-(a.km||0)),'km')}</div></div>
 <div class="note">Неизвестный пробег ТТ не заменяется спутником или нормативом; полный итог км и ₽/км при пропусках не рассчитываются. Источник дополненного пробега виден в деталях заявки. Спутниковые показатели доступны по машине без фильтров водителя, его компании, клиента, исполнителя и типа транспорта; это показатели машины за период. Моточасы — работа двигателя, интервал Excel — длительность спутниковой записи. Расход и моточасы суммируются по дням с показаниями. л / 100 км = расход / пробег × 100 за общие дни. При пропусках пробега в дни рейсов разница не рассчитывается.</div>`;
 $('#group').onchange=e=>{group=e.target.value;render()};$('#statisticsView').onchange=e=>{statisticsView=e.target.value;render()};
 $('#attributeFilters').onsubmit=e=>{e.preventDefault();attributeFilters=Object.fromEntries(new FormData(e.target));render()};
 $('#export').onclick=()=>csv(r.rows.map(a=>({...Object.fromEntries(columns.map(([key,label])=>[label,a[key]])),...(Object.hasOwn(attributeLabels,group)||Object.values(attributeFilters).some(Boolean)?{'Атрибуты':r.attribute_basis}:{}),...(statisticsView==='averages'?{'Формулы':r.average_formulas}:{})})));
 target.querySelectorAll('[data-row]').forEach(el=>el.onclick=()=>{const name=r.rows[el.dataset.row].name;showTrips(r.trips.filter(x=>(group==='pair'?`${x.vehicle} · ${x.driver}`:x[group]||'Не указано')===name),name)});
}

function csv(rows){if(!rows.length)return;const keys=Object.keys(rows[0]);let clean=v=>{v=v!==null&&typeof v==='object'?JSON.stringify(v):String(v??'');if(/^[=+@-]/.test(v))v="'"+v;return '"'+v.replaceAll('"','""')+'"'};let text='\ufeff'+[keys,...rows.map(r=>keys.map(k=>r[k]))].map(r=>r.map(clean).join(';')).join('\r\n');const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='Логистика.csv';a.click();URL.revokeObjectURL(url)}
function tripTable(rows){return table(['№','Дата','Автомобиль','Водитель','Клиент','Тип','Выручка, ₽','Исполнителю, ₽','Км','Часы','Категория'],rows.map(r=>[esc(r.id),esc(r.date),esc(r.vehicle),esc(r.driver),esc(r.client),esc(r.type),fmt(r.revenue),fmt(r.payout),fmt(r.km),fmt(r.hours),esc(r.category)]))}
function showTrips(rows,title){modal(`<div class="panel-head"><h2>${esc(title)}</h2><button data-close>Закрыть</button></div>${tripTable(rows)}<p class="muted">Импортированные записи доступны только для чтения. Исправления вносятся в ТрансТрейде.</p>`)}
function orders(){let rows=D.trips.filter(within);$('#content').innerHTML=`<div class="panel"><div class="panel-head"><h2>${rows.length} записей · исходные данные ТрансТрейда</h2><button id="export">Скачать CSV</button></div>${tripTable(rows)}<p class="muted">Заявки обновляются в разделе «ТрансТрейд». Адреса и логист доступны у записей API. Отменённые заявки исключены из расчётов. «—» — отсутствующий показатель; неполные суммы не выдаются за полный итог.</p></div>`;$('#export').onclick=()=>csv(rows)}
function calendar(){const days=new Date(+calMonth.slice(0,4),+calMonth.slice(5),0).getDate(),key=calMode==='vehicle'?'vehicle':'driver';let trips=D.trips.filter(r=>r.date.startsWith(calMonth)&&r.category==='Рейс'&&!r.cancelled&&(!car||r.vehicle===car)&&(!driver||r.driver===driver)),statuses=D.statuses.filter(r=>r.date.startsWith(calMonth)&&r.kind===key&&(!(key==='vehicle'?car:driver)||r.entity===(key==='vehicle'?car:driver)));let names=[...new Set([...trips.map(r=>r[key]),...statuses.map(r=>r.entity)])].filter(Boolean).sort();$('#content').innerHTML=`<div class="toolbar"><label>Месяц<input id="calMonth" type="month" value="${calMonth}"></label><label>Строки<select id="calMode"><option value="vehicle" ${key==='vehicle'?'selected':''}>Автомобили</option><option value="driver" ${key==='driver'?'selected':''}>Водители</option></select></label><div class="toolbar-actions">${U.role!=='viewer'?'<button id="statusAdd" class="primary">+ Статус / простой</button>':''}</div></div><div class="panel"><div class="panel-head"><h2>Работа и простои · ${calMonth}</h2><span class="muted">Зелёный — рейс · янтарный — статус</span></div><div class="table-wrap"><table class="calendar"><thead><tr><th>${key==='vehicle'?'Автомобиль':'Водитель'}</th>${Array.from({length:days},(_,i)=>`<th>${i+1}</th>`).join('')}</tr></thead><tbody>${names.map((n,ni)=>`<tr><td>${esc(n)}</td>${Array.from({length:days},(_,i)=>{let day=calMonth+'-'+String(i+1).padStart(2,'0'),ts=trips.filter(r=>r[key]===n&&r.date===day),ss=statuses.filter(r=>r.entity===n&&r.date===day);return `<td data-day="${day}" data-name="${ni}">${[...new Set(ts.map(r=>r.client))].map(c=>`<span class="chip">${esc(c)}</span>`).join('')}${ss.map(s=>`<span class="chip status">${esc(s.reason)}</span>`).join('')}${ts.length?`<span class="tag">${ts.length} рейс.</span>`:''}</td>`}).join('')}</tr>`).join('')}</tbody></table>${names.length?'':'<div class="empty">В этом месяце нет фактических записей</div>'}</div></div><div class="panel"><h2>Журнал статусов</h2>${table(['Дата','Объект','Причина','Источник',''],statuses.map(r=>[esc(r.date),esc(r.entity),esc(r.reason),esc(r.source),r.id?`<button data-delete="${esc(r.id)}">Убрать</button>`:'']))}</div>`;$('#calMonth').onchange=e=>{calMonth=e.target.value;calendarFocusDay='';saveNavigationState();calendar()};$('#calMode').onchange=e=>{calMode=e.target.value;calendarFocusDay='';saveNavigationState();calendar()};if($('#statusAdd'))$('#statusAdd').onclick=statusForm;document.querySelectorAll('[data-day]').forEach(el=>el.onclick=()=>{let n=names[el.dataset.name],day=el.dataset.day;showTrips(trips.filter(r=>r[key]===n&&r.date===day),n+' · '+day)});bindDelete();}
function bindDelete(){document.querySelectorAll('[data-delete]').forEach(b=>{const shown=[...D.statuses,...D.plans,...D.trips].find(r=>(r.record_id||r.id)===b.dataset.delete);const body=shown?{revision:shown.revision,delete_token:shown.delete_token}:{};b.onclick=async()=>{try{await api('manual/'+b.dataset.delete,{method:'DELETE',body:JSON.stringify(body)});await refresh();toast('Запись убрана; действие сохранено в журнале')}catch(e){if(e.status===409)showWriteConflict(e);else toast(e.message)}}})}
function dateFields(){return `<label>С<input type="date" name="date" value="${calMonth}-01" required></label><label>По<input type="date" name="end_date" value="${calMonth}-01" required></label>`}
function statusForm(){modal(`<h2>Статус и простой</h2><form class="grid" id="statusForm">${dateFields()}<label>Объект<select name="kind" id="statusKind"><option value="vehicle">Автомобиль</option><option value="driver">Водитель</option></select></label><label>Наименование<select name="entity" id="statusEntity">${options(vehicleNames(),'',null)}</select></label><label>Причина<select name="reason">${options(['Отпуск','Больничный','Выходной','Сервис','Ремонт','Нет заявки','Пересменка','БезВодителя','Другое'],'',null)}</select></label><label>Комментарий<input name="note" maxlength="1000"></label><div class="actions wide"><button type="button" data-close>Отмена</button><button class="primary">Сохранить</button></div></form>`);$('#statusKind').onchange=e=>$('#statusEntity').innerHTML=options(e.target.value==='vehicle'?vehicleNames():Object.keys(D.drivers).sort(),'',null);$('#statusForm').onsubmit=e=>saveForm(e,'statuses');}
async function saveForm(e,kind){e.preventDefault();let b=Object.fromEntries(new FormData(e.target));if(kind==='plans')b.weekdays=[...e.target.querySelectorAll('[name=weekdays]:checked')].map(x=>+x.value);try{const r=await api('manual/'+kind,{method:'POST',body:JSON.stringify(b)});await closeModal();await refresh();toast(`Добавлено записей: ${r.created}. Повторы пропущены.`)}catch(x){toast(x.message)}}
function planner(){const rows=D.plans.filter(r=>r.date.startsWith(calMonth));$('#content').innerHTML=`<div class="toolbar"><label>Месяц<input id="planMonth" type="month" value="${calMonth}"></label><label>Представление<select id="planView" aria-label="Вид планировщика"><option value="list" ${planView==='list'?'selected':''}>Список назначений</option><option value="calendar" ${planView==='calendar'?'selected':''}>Календарь маршрутов</option></select></label><div class="toolbar-actions">${U.role!=='viewer'?'<button id="planAdd" class="primary">+ Назначить маршрут</button>':''}</div></div>${metrics([['Плановые рейсы',fmt(rows.length)],['Выручка, план',money(rows.reduce((a,r)=>a+(r.revenue||0),0))],['Выплаты, план',money(rows.reduce((a,r)=>a+(r.payout||0),0))],['Пробег, план',fmt(rows.reduce((a,r)=>a+(r.km||0),0))+' км']])}<div class="panel"><div class="panel-head"><h2>Назначения водитель → машина → маршрут</h2><button id="export">Скачать CSV</button></div>${planView==='calendar'?planCalendar(rows):table(['Дата','Водитель','Автомобиль / партнёр','Маршрут','Ставка, ₽','Выплата, ₽','Км','Часы','Источник',''],rows.map(r=>[esc(r.date),esc(r.driver),esc(r.vehicle),esc(r.route),fmt(r.revenue),fmt(r.payout),fmt(r.km),fmt(r.hours),esc(r.source),r.id&&!r.id.startsWith('excel:')?`<button data-delete="${esc(r.id)}">Убрать</button>`:'']))}<p class="muted">В исходном справочнике часть автомобилей обозначена именем подрядчика. Это сохранено как ресурс партнёра, а не вымышленный госномер.</p></div>`;$('#planView').onchange=e=>{planView=e.target.value;planner()};$('#planMonth').onchange=e=>{calMonth=e.target.value;planner()};if($('#planAdd'))$('#planAdd').onclick=planForm;$('#export').onclick=()=>csv(rows);bindDelete();}
function planForm(){modal(`<h2>Назначить маршрут на период</h2><form class="grid" id="planForm">${dateFields()}<label>Автомобиль / ресурс партнёра<select name="vehicle">${resourceOptions()}</select></label><label>Водитель<select name="driver">${options(Object.keys(D.drivers).sort(),'',null)}</select></label><label class="wide">Маршрут<select name="route" id="routeSelect">${options(D.routes.map(r=>r.id),'',null)}</select></label><div id="routePreview" class="wide note"></div><div class="checkdays wide">${['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map((d,i)=>`<label><input name="weekdays" type="checkbox" value="${i}" checked>${d}</label>`).join('')}</div><div class="actions wide"><button type="button" data-close>Отмена</button><button class="primary">Сохранить план</button></div></form>`);function preview(){let r=D.routes.find(r=>r.id===$('#routeSelect').value);$('#routePreview').textContent=`Ставка ${money(r.revenue)} · водителю ${money(r.payout)} · партнёру ${money(r.partner_payout)} · ${fmt(r.km)} км · ${fmt(r.hours)} ч`};$('#routeSelect').onchange=preview;preview();$('#planForm').onsubmit=e=>saveForm(e,'plans');}
function comparison(){const plans=D.plans.filter(r=>r.date>=from&&r.date<=to&&(!car||r.vehicle===car)&&(!driver||r.driver===driver));const facts=D.trips.filter(r=>within({...r,client:client||r.client,type:type||r.type})&&r.category==='Рейс');const names=[...new Set([...plans,...facts].map(r=>r.vehicle))].sort();let rows=names.map(n=>{let p=plans.filter(r=>r.vehicle===n),f=facts.filter(r=>r.vehicle===n);const sum=(arr,k)=>arr.length?arr.reduce((a,r)=>a+(r[k]||0),0):null;return {vehicle:n,plan:p.length||null,fact:f.length||null,p:sum(p,'revenue'),f:sum(f,'revenue'),pk:sum(p,'km'),fk:sum(f,'km'),ph:sum(p,'hours'),fh:sum(f,'hours'),pp:sum(p,'payout'),fp:sum(f,'payout')}});$('#content').innerHTML=`<div class="note">Сравнение рейсов; доплаты и удержания отдельно доступны в статистике. План необязателен. «—» означает отсутствие записей, а не нулевую выполненную работу. В исходных книгах план есть за июль и сентябрь, факт — за август. Сравнивайте только периоды с обоими источниками.</div><div class="panel"><h2>План и факт по автомобилям</h2>${table(['Автомобиль','Рейсы план','Рейсы факт','Выручка план','Выручка факт','Отклонение, ₽','Выплаты план','Выплаты факт','Км план','Км факт','Часы план','Часы факт'],rows.map(r=>[esc(r.vehicle),fmt(r.plan),fmt(r.fact),fmt(r.p),fmt(r.f),fmt(r.p!=null&&r.f!=null?r.f-r.p:null),fmt(r.pp),fmt(r.fp),fmt(r.pk),fmt(r.fk),fmt(r.ph),fmt(r.fh)]))}</div>`;}
async function reconciliation(){
 const target=$('#content');const rows=await api('reconcile?'+param());if(target!==$('#content'))return;
 $('#content').innerHTML=`<div class="note">Сверка по машине и дате начала заявки; спутник охватывает полные сутки МСК. Разница = ТТ − спутник. Для ночных рейсов возможен перенос пробега между датами. Моточасы — время работы двигателя, а не длительность рейса. Отсутствующие показания не заменяются нулями; расход по отдельным заявкам или водителям не распределяется. История API заменяет соответствующий показатель Excel без сложения.</div>
 <div class="panel"><div class="panel-head"><h2>Пробег, моточасы и топливо · ${rows.length} машино-дней</h2><button id="export">Скачать CSV</button></div>
 ${table(['Автомобиль','Дата','Рейсы','ТТ, км','Спутник, км','Разница, км','ТТ, ч','Моточасы, ч','Расход, л','л / 100 км','Топливные данные','Источник пробега','Источник моточасов','Интервал Excel, ч','Разница интервалов, ч','Состояние'],rows.map(r=>[esc(r.vehicle),esc(r.date),fmt(r.trips),fmt(r.tt_km),fmt(r.sat_km),`<span class="${Math.abs(r.delta_km||0)>50?'warn':''}">${fmt(r.delta_km)}</span>`,fmt(r.tt_hours),fmt(r.sat_engine_hours),fmt(r.fuel_liters),fmt(r.fuel_l_per_100_km),esc(r.fuel_liters!=null?'Получены':r.fuel_status==='pending'?'Не загружены':r.fuel_status==='suspect_zero'?'Нулевой расход при движении — проверить':'Нет подтверждённых показаний'),esc(r.km_source),esc(r.engine_source),fmt(r.sat_hours),fmt(r.delta_hours),esc(r.state)]),true)}</div>`;
 $('#export').onclick=()=>csv(rows);target.querySelectorAll('[data-row]').forEach(el=>{const row=rows[el.dataset.row];el.setAttribute('aria-label','Заявки и спутник: '+row.vehicle+' · '+row.date);el.onclick=()=>openReconcileDetail(row)});
}

function directories(){$('#content').innerHTML=`<div class="panel"><h2>Маршруты Почты · ${D.routes.length}</h2>${table(['Маршрут','Группа','Ставка, ₽','Водителю, ₽','Партнёру, ₽','Км','Часы','Тариф, ₽/ч'],D.routes.map(r=>[esc(r.id),esc(r.group),fmt(r.revenue),fmt(r.payout),fmt(r.partner_payout),fmt(r.km),fmt(r.hours),fmt(r.rate)]))}<p class="muted">Ставка = время в часах × тариф; исключения исходной книги сохранены. Изменение справочников — через повторный импорт книг.</p></div><div class="split"><div class="panel"><h2>Автомобили</h2>${table(['Наименование','Марка / принадлежность'],Object.entries(D.vehicles).filter(([a])=>isVehicle(a)).map(([a,b])=>[esc(a),esc(b)]))}</div><div class="panel"><h2>Водители</h2>${table(['Водитель','Принадлежность'],Object.entries(D.drivers).map(([a,b])=>[esc(a),esc(b)]))}</div></div><div class="panel"><h2>Ресурсы партнёров и прочие обозначения источника</h2><p class="muted">Эти записи не являются госномерами и не предлагаются в фильтре автомобилей.</p>${table(['Наименование','Принадлежность'],Object.entries(D.vehicles).filter(([a])=>!isVehicle(a)).map(([a,b])=>[esc(a),esc(b)]))}</div>`;}
async function connections(){const target=$('#content');let rows=await api('connections');if(target!==$('#content'))return;$('#content').innerHTML=`<div class="panel"><div class="panel-head"><h2>Состояние источников</h2>${U.role==='admin'?'<button id="checkConnections">Проверить соединения</button>':''}</div>${rows.map(r=>`<div class="connection"><div><h2><a href="${pagePath(r.id)}">${esc(r.name)}</a></h2><a href="${pagePath(r.id)}">Открыть подключение →</a></div><span class="badge">${esc(r.status)}</span></div>`).join('')}</div><div class="panel"><div class="panel-head"><h2>Excel-снимок</h2>${U.role==='admin'?'<button id="reimport" class="primary">Обновить из исходных Excel</button>':''}</div><p>Последний импорт: ${new Date(D.meta.imported_at).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'})} МСК</p>${table(['Источник','Контрольная сумма SHA-256'],D.meta.files.map(f=>[esc(f.name),`<code>${esc(f.sha256)}</code>`]))}<p>${Object.entries(D.meta.counts).map(([k,v])=>`${esc(k)}: ${v}`).join(' · ')}</p>${U.role==='admin'?'<form id="upload" class="grid"><label>Книга статистики<input type="file" name="statistics" accept=".xlsx" required></label><label>Книга планировщика<input type="file" name="planner" accept=".xlsx" required></label><div class="wide"><button>Импортировать новые книги</button></div></form>':''}<p class="muted">Импорт добавляет периоды в рабочую базу. Назначения, их сохранённые ставки и ручные исправления остаются; повторные записи не добавляются. Изменённые назначения редактируйте в планировщике. Исходные файлы не изменяются. Файл доступов сюда загружать не нужно.</p></div><div class="panel"><h2>Качество данных</h2><p>56 ошибок #REF! на листе «Анализ» исходной статистики. В приложении показатели рассчитываются из записей, без сломанных ссылок. ${D.meta.issues.length?esc(D.meta.issues.join('; ')):'Неизвестных маршрутов и объектов при импорте не обнаружено.'}</p></div>`;if($('#checkConnections'))$('#checkConnections').onclick=async e=>{e.target.disabled=true;e.target.textContent='Проверка…';try{await api('connections/check',{method:'POST',body:'{}'});await connections();toast('Проверка соединений завершена')}catch(x){toast(x.message);e.target.disabled=false}};if($('#reimport'))$('#reimport').onclick=async e=>{e.target.disabled=true;try{await api('import',{method:'POST',body:'{}'});await refresh();toast('Снимок обновлён из исходных книг')}catch(x){toast(x.message);e.target.disabled=false}};if($('#upload'))$('#upload').onsubmit=async e=>{e.preventDefault();try{await api('import',{method:'POST',body:new FormData(e.target)});await refresh();toast('Книги импортированы')}catch(x){toast(x.message)}};}
async function users(){const target=$('#content');const [rows,logs]=await Promise.all([api('users'),api('audit')]);if(target!==$('#content'))return;$('#content').innerHTML=`<div class="note">Предложенная матрица: руководитель управляет импортом и доступами; логист смотрит отчёты и вводит планы/статусы по назначенным машинам; наблюдатель только смотрит. Права проверяются сервером.</div><div class="panel"><h2>Пользователи</h2>${table(['Имя','Роль','Назначенные машины'],rows.map(r=>[esc(r.name),esc(r.role),esc(JSON.parse(r.vehicles).join(', '))]),false,false)}<form id="userForm" class="grid" style="margin-top:20px"><label>Имя<input name="name" required></label><label>Пароль<input name="password" type="password" minlength="12" required autocomplete="new-password"></label><label>Роль<select name="role"><option value="logist">Логист</option><option value="viewer">Наблюдатель</option><option value="admin">Руководитель</option></select></label><label>Машины<select name="vehicles" multiple>${options(vehicleNames(),'',null)}</select></label><div class="wide"><button class="primary">Добавить пользователя</button></div></form></div><div class="panel"><h2>Журнал действий</h2>${table(['Время UTC','Пользователь','Действие','Детали'],logs.map(r=>[esc(r.at),esc(r.user_id),esc(r.action),esc(r.detail)]),false,false)}</div>`;$('#userForm').onsubmit=async e=>{e.preventDefault();let b=Object.fromEntries(new FormData(e.target));b.vehicles=[...e.target.elements.vehicles.selectedOptions].map(o=>o.value);try{await api('users',{method:'POST',body:JSON.stringify(b)});await users();toast('Пользователь добавлен')}catch(x){toast(x.message)}};}
async function refresh(){D=await api('data');await render()}
async function boot(){const s=await api('session');csrf=s.csrf;U=s.user;if(!U){$('#app').innerHTML=`<main class="auth-page"><div class="auth-shell"><section class="auth-story" aria-labelledby="auth-title"><a class="auth-brand" href="/" aria-label="Логистика — главная"><span class="auth-mark" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none"><path d="M8 23V9h9a5 5 0 0 1 0 10H8m9 0 7 5" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/><circle cx="8" cy="9" r="3" fill="currentColor"/></svg></span>Логистика<span class="auth-brand-dot">.</span></a><div class="auth-story-copy"><p class="auth-eyebrow">ВАШ АВТОПАРК. ОБЩАЯ КАРТИНА.</p><h1 id="auth-title">Планируйте рейсы.<br><span>Смотрите результат.</span></h1><p class="auth-lead">Маршруты, люди и цифры —<br>в одном рабочем пространстве.</p></div><ol class="auth-features"><li><span class="auth-feature-icon auth-blue" aria-hidden="true">↗</span><div><strong>Планирование</strong><span>Маршруты, автомобили и водители</span></div><small>01</small></li><li><span class="auth-feature-icon auth-dark" aria-hidden="true">≋</span><div><strong>Данные</strong><span>Заявки, топливо и показания</span></div><small>02</small></li><li><span class="auth-feature-icon auth-green" aria-hidden="true">✓</span><div><strong>Аналитика</strong><span>План, факт и экономика</span></div><small>03</small></li></ol><p class="auth-story-footer">От маршрута к результату <span aria-hidden="true">→</span></p></section><section class="auth-entry" aria-labelledby="auth-welcome"><div class="auth-entry-top"><span class="auth-lock" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 4v3"/></svg></span><span class="auth-eyebrow">РАБОЧЕЕ ПРОСТРАНСТВО</span></div><h2 id="auth-welcome">Рады видеть вас</h2><p class="auth-entry-lead">Войдите, чтобы продолжить<br>работу с автопарком.</p><form id="login" class="auth-form"><label for="auth-name">Логин</label><input id="auth-name" name="name" autocomplete="username" placeholder="Введите логин" required autocapitalize="none" spellcheck="false"><label for="auth-password">Пароль</label><input id="auth-password" name="password" type="password" autocomplete="current-password" placeholder="Введите пароль" required><p id="auth-error" class="auth-error" role="alert" hidden></p><button class="primary auth-submit" type="submit"><span>Войти в рабочее пространство</span><span aria-hidden="true">→</span></button></form><p class="auth-private"><span aria-hidden="true">◇</span> Доступ по учётной записи</p><p class="auth-help">Нет доступа? Обратитесь к администратору.</p></section></div></main>`;$('#login').onsubmit=async e=>{e.preventDefault();const form=e.target,button=form.querySelector('button[type=submit]'),error=$('#auth-error');button.disabled=true;form.setAttribute('aria-busy','true');error.hidden=true;try{await api('login',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(form)))});await boot()}catch(x){error.textContent=x.message;error.hidden=false}finally{button.disabled=false;form.removeAttribute('aria-busy')}};return}tab=pageFromURL();if(tab==='users'&&U.role!=='admin')tab='statistics';history.replaceState(null,'',pagePath(tab));await refresh()}
// Boot after workspace extensions are loaded.

function planCalendar(rows){const names=[...new Set(rows.map(r=>r.vehicle))].sort(),days=new Date(+calMonth.slice(0,4),+calMonth.slice(5),0).getDate();return '<div class="table-wrap"><table class="calendar"><thead><tr><th>Автомобиль / партнёр</th>'+Array.from({length:days},(_,i)=>`<th>${i+1}</th>`).join('')+'</tr></thead><tbody>'+names.map(n=>`<tr><td>${esc(n)}</td>`+Array.from({length:days},(_,i)=>{const day=calMonth+'-'+String(i+1).padStart(2,'0');return '<td>'+rows.filter(r=>r.vehicle===n&&r.date===day).map(r=>`<span class="chip plan">${esc(r.route)}<br>${esc(r.driver)}</span>`).join('')+'</td>'}).join('')+'</tr>').join('')+'</tbody></table></div>'}

// Shared table controls preserve original row nodes and their detail/delete handlers.
function enhanceTables(root=document){
 root.querySelectorAll('.table-wrap').forEach(w=>{
  if(w.dataset.enhanced)return;w.dataset.enhanced='true';
  w.tabIndex=0;w.setAttribute('role','region');w.setAttribute('aria-label','Таблица с прокруткой');
  const hint=document.createElement('p');hint.className='table-hint';hint.textContent='↔ Таблицу можно прокручивать вправо';hint.hidden=true;w.after(hint);const updateHint=()=>{hint.hidden=w.scrollWidth<=w.clientWidth+1};requestAnimationFrame(updateHint);if(typeof ResizeObserver!=='undefined'){const resize=new ResizeObserver(()=>{if(!w.isConnected){resize.disconnect();return}updateHint()});resize.observe(w)}
  const t=w.querySelector('table');if(!t||t.classList.contains('calendar'))return;
  const rows=[...t.tBodies[0].rows];if(!rows.length)return;
  if(!w.hasAttribute('data-no-search')){
   const tools=document.createElement('div');tools.className='table-tools';
   tools.innerHTML='<label class="table-search"><input type="search" aria-label="Поиск в таблице" placeholder="Поиск в таблице"></label>';
   w.before(tools);
   const empty=document.createElement('div');empty.className='empty';empty.hidden=true;empty.textContent='Совпадений нет. Измените поисковый запрос.';w.append(empty);
   tools.querySelector('input').oninput=e=>{const q=e.target.value.trim().toLocaleLowerCase('ru');let n=0;rows.forEach(r=>{r.hidden=!r.textContent.toLocaleLowerCase('ru').includes(q);if(!r.hidden)n++});empty.hidden=n>0;};
  }
  [...t.tHead.rows[0].cells].forEach((th,i)=>{const b=th.querySelector('.sort');if(!b)return;b.onclick=()=>{
   const asc=th.getAttribute('aria-sort')!=='ascending';t.querySelectorAll('th').forEach(h=>h.setAttribute('aria-sort','none'));th.setAttribute('aria-sort',asc?'ascending':'descending');
   const val=r=>r.cells[i].textContent.trim();const number=v=>{const date=v.match(/^(\d{2})\.(\d{2})\.(\d{4})(?:,? (\d{2}):(\d{2})(?::(\d{2}))?)?(?: МСК)?$/);if(date)return Date.UTC(+date[3],+date[2]-1,+date[1],+(date[4]||0),+(date[5]||0),+(date[6]||0));const x=v.replace(/[\s₽]/g,'').replace(',','.');return /^-?\d+(\.\d+)?$/.test(x)?Number(x):null};
   [...rows].sort((a,b)=>{const x=val(a),y=val(b);if(x==='—'||y==='—')return x===y?0:x==='—'?1:-1;const nx=number(x),ny=number(y);return (nx!==null&&ny!==null?nx-ny:x.localeCompare(y,'ru',{numeric:true}))*(asc?1:-1)}).forEach(r=>t.tBodies[0].append(r));
  }});
  rows.filter(r=>r.classList.contains('clickable')).forEach(r=>r.onkeydown=e=>{if(e.target===r&&(e.key==='Enter'||e.key===' ')){e.preventDefault();r.click()}});
 });
}
// Share the table heading row without recreating controls or their event handlers.
function compactTableTools(root=document){
 root.querySelectorAll('.table-tools').forEach(tools=>{
  if(tools.closest('.compact-table-head'))return;
  const wrap=tools.nextElementSibling;
  if(!wrap?.classList.contains('table-wrap'))return;
  let head=tools.previousElementSibling;
  while(head&&!head.matches('.panel-head,h2,h3,.table-wrap,.table-tools'))head=head.previousElementSibling;
  if(!head||head.matches('.table-wrap,.table-tools'))return;
  if(head.matches('h2,h3')){const row=document.createElement('div');row.className='panel-head';head.before(row);row.append(head);head=row}
  if(head.querySelector('.table-tools'))return;
  head.classList.add('compact-table-head');
  const actions=head.querySelector(':scope>div:not(.search-select)');
  if(actions&&!actions.matches('.toolbar-actions')){actions.classList.add('compact-table-actions');actions.prepend(tools)}
  else {const heading=head.querySelector('h2,h3');if(heading)heading.after(tools);else head.prepend(tools)}
 });
}

new MutationObserver(()=>{enhanceTables();compactTableTools();compactFieldLabels();enhanceSelects()}).observe(document.getElementById('app'),{childList:true,subtree:true});
new MutationObserver(()=>{enhanceTables(document.getElementById('dialog'));compactTableTools(document.getElementById('dialog'));compactFieldLabels(document.getElementById('dialog'));enhanceSelects(document.getElementById('dialog'))}).observe(document.getElementById('dialog'),{childList:true,subtree:true});

function positionCapsule(){requestAnimationFrame(()=>{const nav=$('.sidebar nav'),active=nav?.querySelector('.active'),pill=nav?.querySelector('.nav-capsule');if(!active)return;pill.getBoundingClientRect();pill.style.transform=`translateY(${active.offsetTop}px)`;pill.style.height=active.offsetHeight+'px';pill.style.opacity='1';})}
window.addEventListener('resize',positionCapsule);
function closeSidebar({focus=false}={}){const toggle=$('#menu-toggle');$('.sidebar.is-open')?.classList.remove('is-open');if(!toggle)return;toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-label','Открыть навигацию');if(focus)toggle.focus()}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('.sidebar.is-open'))closeSidebar({focus:true})});
document.addEventListener('click',e=>{if($('.sidebar.is-open')&&!e.target.closest('.sidebar,#menu-toggle'))closeSidebar()});
const chartDate=d=>new Date(d+'T00:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'short'}).replace('.','');
const chartValue=x=>new Intl.NumberFormat('ru-RU',{notation:'compact',maximumFractionDigits:1}).format(x);
function reconcileTimeline(rows){
 const daily=Object.values(rows.reduce((out,r)=>{const v=out[r.date]??={from:r.date,to:r.date,tt:0,sat:0,matched:0,missing:0,noOrders:0};v.to=r.date;if(r.state==='Сопоставлено'){v.tt+=r.tt_km??0;v.sat+=r.sat_km??0;v.matched++}else if(['Нет спутника','Нет пробега ТТ'].includes(r.state))v.missing++;else if(r.state==='Нет заявок')v.noOrders++;return out},{})).sort((a,b)=>a.from.localeCompare(b.from));
 const size=daily.length>45?7:1;if(size===1)return daily;
 const grouped=[];for(let i=0;i<daily.length;i+=size){const slice=daily.slice(i,i+size),v={from:slice[0].from,to:slice.at(-1).to,tt:0,sat:0,matched:0,missing:0,noOrders:0};slice.forEach(r=>Object.keys(v).filter(k=>!['from','to'].includes(k)).forEach(k=>v[k]+=r[k]));grouped.push(v)}return grouped;
}
function chartLabels(rows,x){
 const indexes=rows.length<4?rows.map((_,i)=>i):[0,Math.round((rows.length-1)/2),rows.length-1];
 return [...new Set(indexes)].map(i=>`<text x="${x(i)}" y="224" text-anchor="${i===0?'start':i===rows.length-1?'end':'middle'}">${esc(chartDate(rows[i].from))}</text>`).join('');
}
function mileageTimeline(rows){
 if(!rows.length||!rows.some(r=>r.matched))return '<div class="chart-empty">Нет сопоставленных данных для динамики</div>';
 const w=720,h=236,left=48,right=12,top=14,bottom=30,pw=w-left-right,ph=h-top-bottom,max=Math.max(1,...rows.flatMap(r=>[r.tt,r.sat]));
 const x=i=>left+(rows.length===1?pw/2:i*pw/(rows.length-1)),y=v=>top+ph-v/max*ph,path=k=>rows.map((r,i)=>(i?'L':'M')+x(i).toFixed(1)+' '+y(r[k]).toFixed(1)).join(' ');
 const grid=[0,.25,.5,.75,1].map(p=>`<g class="chart-grid" aria-hidden="true"><line x1="${left}" y1="${top+ph*(1-p)}" x2="${w-right}" y2="${top+ph*(1-p)}"/><text x="${left-9}" y="${top+ph*(1-p)+4}" text-anchor="end">${chartValue(max*p)}</text></g>`).join('');
 const hit=Math.max(12,pw/Math.max(1,rows.length)),points=rows.map((r,i)=>{const period=chartDate(r.from)+(r.to!==r.from?' — '+chartDate(r.to):''),label=`${period}: ТрансТрейд ${fmt(r.tt)} км; спутник ${fmt(r.sat)} км; разница ${fmt(r.tt-r.sat)} км. Открыть сверку`;return `<g class="chart-hit chart-drill${rows.length===1?' chart-single':''}" tabindex="0" focusable="true" role="link" aria-label="${esc(label)}" data-chart-from="${r.from}" data-chart-to="${r.to}"><title>${esc(label)}</title><rect x="${x(i)-hit/2}" y="${top}" width="${hit}" height="${ph}"/><circle class="chart-point tt" cx="${x(i)}" cy="${y(r.tt)}" r="4"/><circle class="chart-point sat" cx="${x(i)}" cy="${y(r.sat)}" r="4"/></g>`}).join('');
 const peak=rows.reduce((a,r)=>Math.abs(r.tt-r.sat)>Math.abs(a.tt-a.sat)?r:a,rows[0]);
 return `<div class="chart-scroll"><svg class="timeline-chart" viewBox="0 0 ${w} ${h}" role="group" aria-label="Динамика пробега. Наибольший разрыв ${fmt(Math.abs(peak.tt-peak.sat))} километров за ${chartDate(peak.from)}">${grid}<path class="chart-line tt" aria-hidden="true" d="${path('tt')}"/><path class="chart-line sat" aria-hidden="true" d="${path('sat')}"/>${points}<g class="chart-axis" aria-hidden="true">${chartLabels(rows,x)}</g></svg></div>`;
}
function coverageTimeline(rows){
 if(!rows.length)return '<div class="chart-empty">Нет данных о покрытии за выбранный период</div>';
 const w=720,h=236,left=34,right=12,top=14,bottom=30,pw=w-left-right,ph=h-top-bottom,slot=pw/rows.length,gap=Math.min(8,Math.max(2,slot*.28)),bar=Math.max(2,slot-gap),x=i=>left+i*slot+gap/2;
 const grid=[0,.5,1].map(p=>`<g class="chart-grid" aria-hidden="true"><line x1="${left}" y1="${top+ph*(1-p)}" x2="${w-right}" y2="${top+ph*(1-p)}"/><text x="${left-8}" y="${top+ph*(1-p)+4}" text-anchor="end">${p*100}%</text></g>`).join('');
 const bars=rows.map((r,i)=>{const total=r.matched+r.missing+r.noOrders,y0=top+ph,mh=total?r.matched/total*ph:0,gh=total?r.missing/total*ph:0,nh=total?r.noOrders/total*ph:0,period=chartDate(r.from)+(r.to!==r.from?' — '+chartDate(r.to):''),label=`${period}: оба источника ${r.matched}; нет данных ТТ / спутника ${r.missing}; нет заявок ${r.noOrders}. Открыть сверку`;return `<g class="coverage-column chart-drill" tabindex="0" focusable="true" role="link" aria-label="${esc(label)}" data-chart-from="${r.from}" data-chart-to="${r.to}"><title>${esc(label)}</title><rect class="column-bg" x="${x(i)}" y="${top}" width="${bar}" height="${ph}" rx="${Math.min(4,bar/2)}"/><rect class="column-matched" x="${x(i)}" y="${y0-mh}" width="${bar}" height="${mh}"/><rect class="column-missing" x="${x(i)}" y="${y0-mh-gh}" width="${bar}" height="${gh}"/><rect class="column-no-orders" x="${x(i)}" y="${y0-mh-gh-nh}" width="${bar}" height="${nh}"/></g>`}).join('');
 return `<div class="chart-scroll"><svg class="timeline-chart" viewBox="0 0 ${w} ${h}" role="group" aria-label="Доля сопоставленных данных, пропусков спутника и дней без заявок по датам">${grid}${bars}<g class="chart-axis" aria-hidden="true">${chartLabels(rows,i=>x(i)+bar/2)}</g></svg></div>`;
}
async function dashboard(){
 const target=$('#content'),rows=await api('reconcile?'+param());if(target!==$('#content'))return;
 const matched=rows.filter(r=>r.state==='Сопоставлено'),missing=rows.filter(r=>['Нет спутника','Нет пробега ТТ'].includes(r.state)),noOrders=rows.filter(r=>r.state==='Нет заявок');
 const sum=(rs,k)=>rs.reduce((n,r)=>n+(r[k]??0),0),tt=sum(matched,'tt_km'),sat=sum(matched,'sat_km'),coverage=rows.length?matched.length/rows.length*100:0;
 const ranked=[...matched].sort((a,b)=>Math.abs(b.delta_km)-Math.abs(a.delta_km)),alerts=ranked.filter(r=>Math.abs(r.delta_km)>50);
 const cars=Object.values(matched.reduce((out,r)=>{const v=out[r.vehicle]??={name:r.vehicle,tt:0,sat:0,delta:0};v.tt+=r.tt_km;v.sat+=r.sat_km;v.delta+=Math.abs(r.delta_km);return out},{})).sort((a,b)=>b.delta-a.delta).slice(0,8),max=Math.max(1,...cars.flatMap(r=>[r.tt,r.sat])),timeline=reconcileTimeline(rows);
 $('#content').innerHTML=`${metrics([['Сопоставлено',fmt(matched.length)+' / '+fmt(rows.length),'Машино-дней с данными обоих источников'],['Расхождение пробега',(matched.length?fmt(tt-sat):'—')+' км','ТТ − спутник · только сопоставленные дни'],['Требуют проверки',fmt(alerts.length),'Машино-дней с разницей более 50 км'],['Не хватает данных',fmt(missing.length),'Отсутствующие данные, а не нулевой пробег']])}
 <div class="split dashboard-charts"><section class="panel"><div class="panel-head"><h2>Покрытие сверкой</h2><span class="badge">${esc(from)} — ${esc(to)}</span></div><div class="coverage"><div class="coverage-ring" style="background:conic-gradient(#0071e3 0 ${coverage}%,#d49642 ${coverage}% ${rows.length?(matched.length+missing.length)/rows.length*100:0}%,#ececf2 0)" role="img" aria-label="Сопоставлено ${fmt(coverage)} процентов"><div><strong>${rows.length?fmt(coverage)+'%':'—'}</strong><span>сопоставлено</span></div></div><div class="coverage-legend"><p><i class="legend-dot blue"></i>Оба источника <b>${fmt(matched.length)}</b></p><p><i class="legend-dot amber"></i>Нет данных ТТ / спутника <b>${fmt(missing.length)}</b></p><p><i class="legend-dot gray"></i>Нет заявок <b>${fmt(noOrders.length)}</b></p><button id="open-reconcile">Открыть сверку →</button></div></div><p class="muted">Один машино-день — один автомобиль за одну дату. Покрытие считается по объединению дат обоих источников.</p></section>
 <section class="panel"><h2>Пробег по автомобилям</h2><p class="muted"><i class="legend-dot blue"></i>ТрансТрейд <i class="legend-dot purple"></i>Спутник · км</p>${cars.map(r=>`<div class="paired-row vehicle-drill" tabindex="0" role="link" aria-label="Открыть сверку по автомобилю ${esc(r.name)}" data-chart-vehicle="${esc(r.name)}"><span>${esc(r.name)}</span><div><div class="paired-bar"><i style="width:${r.tt/max*100}%"></i><span>${fmt(r.tt)}</span></div><div class="paired-bar satellite"><i style="width:${r.sat/max*100}%"></i><span>${fmt(r.sat)}</span></div></div></div>`).join('')||'<div class="empty">Нет сопоставленных данных</div>'}<p class="muted">Нажмите на автомобиль, чтобы открыть его сверку. Показаны до 8 машин с наибольшей суммой абсолютных дневных расхождений.</p></section></div>
 <div class="split dashboard-trends"><section class="panel"><div class="panel-head"><div><h2>Пробег по дням</h2><span class="badge">только сопоставленные</span></div></div><div class="chart-legend"><span><i class="legend-dot blue"></i>ТрансТрейд</span><span><i class="legend-dot purple"></i>Спутник</span><small>км</small></div>${mileageTimeline(timeline)}<p class="muted chart-caption">Нажмите на точку, чтобы открыть сверку за выбранную дату. Обе линии построены по одинаковому набору машино-дней.</p></section>
 <section class="panel"><div class="panel-head"><div><h2>Покрытие по дням</h2><span class="badge">доля машино-дней</span></div></div><div class="chart-legend"><span><i class="legend-dot blue"></i>Оба источника</span><span><i class="legend-dot amber"></i>Нет данных ТТ / спутника</span><span><i class="legend-dot gray"></i>Нет заявок</span></div>${coverageTimeline(timeline)}<p class="muted chart-caption">Нажмите на столбец, чтобы открыть сверку и точные записи за выбранную дату.</p></section></div>
 <section class="panel"><div class="panel-head"><div><h2>Что проверить в первую очередь</h2><span class="badge">Разница больше 50 км</span></div><button id="dashboard-export">Скачать список CSV</button></div>${table(['Автомобиль','Дата','ТТ, км','Спутник, км','Разница, км','Разница, ч'],alerts.slice(0,20).map(r=>[esc(r.vehicle),esc(r.date),fmt(r.tt_km),fmt(r.sat_km),`<span class="warn">${fmt(r.delta_km)}</span>`,fmt(r.delta_hours)]),true)}<p class="muted">${alerts.length?'Показаны первые '+Math.min(20,alerts.length)+' из '+alerts.length+'. Нажмите строку, чтобы открыть рейсы.':(matched.length?'Дней с расхождением более 50 км нет.':'Нет сопоставленных данных для оценки расхождений.')} CSV содержит весь список. Расхождение — повод проверить записи, само по себе оно не доказывает нарушение.</p></section>`;
 const activate=(el,open)=>{el.onclick=open;el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open()}}};
 document.querySelectorAll('[data-chart-from]').forEach(el=>activate(el,()=>{navigate('reconcile',{preserveFilters:true,filters:{from:el.dataset.chartFrom,to:el.dataset.chartTo}})}));
 document.querySelectorAll('[data-chart-vehicle]').forEach(el=>activate(el,()=>{navigate('reconcile',{preserveFilters:true,filters:{car:el.dataset.chartVehicle}})}));
 $('#open-reconcile').onclick=()=>{navigate('reconcile')};$('#dashboard-export').onclick=()=>csv(alerts);target.querySelectorAll('[data-row]').forEach(el=>el.onclick=()=>openReconcileDetail(alerts[el.dataset.row]));
}


// RouteDesk motion: spring 300/35/1 for dialogs, 500/45/1 for controls.
const reducedMotion=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
function springFrames(stiffness,damping,frame){
 const d=Math.sqrt(damping*damping-4*stiffness),a=(-damping+d)/2,b=(-damping-d)/2;
 return Array.from({length:61},(_,i)=>{const t=i/60*.65,p=1-(-b*Math.exp(a*t)+a*Math.exp(b*t))/(a-b);return {...frame(i===60?1:p),offset:i/60}});
}
function animateSurface(el){if(!reducedMotion())el.animate(springFrames(300,35,p=>({opacity:Math.min(1,p*2),transform:`translateX(${60*(1-p)}px)`})),{duration:650,easing:'linear'})}
async function closeModal(){const d=$('#dialog');if(d.dataset.closing)return;d.dataset.closing='true';if(!reducedMotion())await d.animate([{opacity:1,transform:'translateX(0)'},{opacity:0,transform:'translateX(60px)'}],{duration:240,easing:'ease-in'}).finished;d.close();delete d.dataset.closing}
function isVehicle(name){return /^[A-ZА-ЯЁ]\d{3}[A-ZА-ЯЁ]{2}\d{2,3}$/i.test(name.replace(/\s/g,''))}
function vehicleNames(){return Object.keys(D.vehicles).filter(isVehicle).sort()}
function positionMonthPill(){const box=$('.months');if(!box)return;let pill=box.querySelector('.month-pill');if(!pill){pill=document.createElement('i');pill.className='month-pill';pill.setAttribute('aria-hidden','true');box.prepend(pill)}const selected=box.querySelector('.selected');box.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===selected)));if(!selected){pill.style.opacity=0;return}const previous=pill.getBoundingClientRect();pill.style.cssText=`left:${selected.offsetLeft}px;top:${selected.offsetTop}px;width:${selected.offsetWidth}px;height:${selected.offsetHeight}px;opacity:1`;if(previous.width&&!reducedMotion()){const next=pill.getBoundingClientRect();pill.animate(springFrames(500,45,p=>({transform:`translate(${(previous.x-next.x)*(1-p)}px,${(previous.y-next.y)*(1-p)}px) scaleX(${1+(previous.width/next.width-1)*(1-p)})`})),{duration:650})}}
window.addEventListener('resize',positionMonthPill);
let selectSerial=0;
function compactFieldLabels(root=document){
 root.querySelectorAll('label').forEach(label=>{
  if(label.dataset.compactField)return;
  const control=label.querySelector('select,input,textarea');
  if(!control||['checkbox','radio','hidden','submit','button'].includes(control.type))return;
  const textNodes=[...label.childNodes].filter(n=>n.nodeType===3);
  const name=textNodes.map(n=>n.textContent).join(' ').trim();
  if(!name)return;
  label.dataset.compactField='true';
  if(!control.hasAttribute('aria-label'))control.setAttribute('aria-label',name);
  control.title=control.title||name;
  if(['date','month','datetime-local','time','file','color','range'].includes(control.type)){
   label.classList.add('inline-field-label');return;
  }
  if(control.tagName==='SELECT'){
   control.dataset.placeholder=name;
   const empty=[...control.options].find(o=>o.value==='');
   if(empty)empty.textContent=name;
  }else control.placeholder=name;
  textNodes.forEach(n=>n.remove());
 });
}

function enhanceSelects(root=document){
 root.querySelectorAll('select').forEach(select=>{
  if(select.id==='group'||select.dataset.searchable||!(select.multiple||select.options.length>6||['car','driver','client','statusEntity','routeSelect'].includes(select.id)||['vehicle','driver'].includes(select.name)))return;
  select.dataset.searchable='true';const wrapper=document.createElement('div');wrapper.className='search-select';select.before(wrapper);wrapper.append(select);select.hidden=true;
  const input=document.createElement('input');input.type='text';input.autocomplete='off';input.placeholder=select.dataset.placeholder||'Выбрать из справочника…';input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-expanded','false');
  input.setAttribute('aria-label',select.getAttribute('aria-label')||select.closest('label')?.firstChild.textContent.trim()||'Выбор из справочника');
  const list=document.createElement('div');list.className='select-options';list.id='choices-'+ ++selectSerial;list.hidden=true;list.setAttribute('popover','manual');list.setAttribute('role','listbox');if(select.multiple)list.setAttribute('aria-multiselectable','true');input.setAttribute('aria-controls',list.id);wrapper.append(input,list);
  let active=-1,filtered=[];const sync=()=>{input.value=[...select.selectedOptions].filter(o=>!select.dataset.placeholder||o.value!=='').map(o=>o.textContent).join(', ')};
  const close=()=>{if(list.matches(':popover-open'))list.hidePopover();list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');sync()};
  const highlight=()=>{[...list.children].forEach((n,i)=>n.classList.toggle('focused',i===active));if(active>=0){input.setAttribute('aria-activedescendant',list.children[active].id);list.children[active].scrollIntoView({block:'nearest'})}else input.removeAttribute('aria-activedescendant')};
  const choose=i=>{const o=filtered[i];if(!o)return;if(select.multiple)o.selected=!o.selected;else select.value=o.value;select.dispatchEvent(new Event('change',{bubbles:true}));if(select.multiple){draw();input.focus()}else close()};
  const draw=()=>{const q=input.value.trim().toLocaleLowerCase('ru');filtered=[...select.options].filter(o=>!o.disabled&&o.textContent.toLocaleLowerCase('ru').includes(q));list.replaceChildren();filtered.forEach((o,i)=>{const row=document.createElement('div');row.id=list.id+'-'+i;row.setAttribute('role','option');row.setAttribute('aria-selected',String(o.selected));row.textContent=(o.parentElement.tagName==='OPTGROUP'&&o.parentElement.label!=='Автомобили'?'Ресурс партнёра: ':'')+(select.multiple?(o.selected?'☑ ':'☐ '):'')+o.textContent;row.onpointerdown=e=>{e.preventDefault();choose(i)};list.append(row)});if(!filtered.length){const empty=document.createElement('p');empty.textContent='Ничего не найдено';list.append(empty)}active=-1;highlight()};
  const place=()=>{if(list.hidden)return;const r=input.getBoundingClientRect(),gap=6,below=innerHeight-r.bottom-12,above=r.top-12,up=below<180&&above>below;const height=Math.min(280,Math.max(80,up?above:below));list.style.cssText=`position:fixed;margin:0;inset:auto;width:${Math.min(Math.max(r.width,260),innerWidth-24)}px;max-height:${height}px;left:${Math.max(12,Math.min(r.left,innerWidth-Math.max(r.width,260)-12))}px;${up?'bottom:'+ (innerHeight-r.top+gap):'top:'+(r.bottom+gap)}px`;};const open=()=>{if(!list.hidden)return;input.value='';list.hidden=false;input.setAttribute('aria-expanded','true');draw();list.showPopover();place();};
  input.onfocus=open;input.onclick=open;input.oninput=()=>{open();draw()};input.onblur=close;list.addEventListener('wheel',e=>e.stopPropagation(),{passive:true});const reposition=()=>{if(!list.hidden)place()};window.addEventListener('resize',reposition);window.addEventListener('scroll',reposition,true);const cleanup=new MutationObserver(()=>{if(!wrapper.isConnected){window.removeEventListener('resize',reposition);window.removeEventListener('scroll',reposition,true);cleanup.disconnect()}});cleanup.observe(document.getElementById('app'),{childList:true,subtree:true});cleanup.observe(document.getElementById('dialog'),{childList:true,subtree:true});
  input.onkeydown=e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();open();active=Math.max(0,Math.min(filtered.length-1,active+(e.key==='ArrowDown'?1:-1)));highlight()}else if(e.key==='Enter'&&!list.hidden){e.preventDefault();choose(active<0?0:active)}else if(e.key==='Escape'&&!list.hidden){e.preventDefault();e.stopPropagation();close()}else if(e.key==='Tab')close()};
  select.addEventListener('change',()=>{if(list.hidden)sync()});new MutationObserver(()=>{if(list.hidden)sync();else draw()}).observe(select,{childList:true,subtree:true});sync();
 });
}

function resourceOptions(){return `<optgroup label="Автомобили">${options(vehicleNames(),'',null)}</optgroup><optgroup label="Ресурсы партнёров / обозначения источника">${options(Object.keys(D.vehicles).filter(n=>!isVehicle(n)).sort(),'',null)}</optgroup>`}


async function loadNeftmPanel(){
 const panel=$('#neftm-panel');if(!panel)return;
 try{
  const state=await api('neftm');if(panel!==$('#neftm-panel'))return;
  drawNeftmPanel(panel,state);
 }catch(e){if(panel.isConnected)panel.innerHTML=`<h2>Нефтьмагистраль · транзакции</h2><p role="alert">${esc(e.message)}</p>`}
}
function drawNeftmPanel(panel,state){
 const snap=state.snapshot,rows=snap?.rows||[];
 const columns=[['dateRec','Дата и время, МСК'],['cardNumber','Карта'],['cardHolder','Держатель'],['serviceName','Услуга'],['amount','Количество'],['priceClient','Цена'],['costClient','Сумма'],['currencyName','Валюта / кошелёк'],['typeNumber','Тип операции'],['posNum','Номер ТО'],['terminalNum','Терминал']];
 const kind=r=>r.typeNumber==='11'?'Обслуживание':r.typeNumber==='24'?'Возврат на счёт':`Тип ${r.typeNumber}`;
 panel.innerHTML=`<div class="panel-head"><h2>Нефтьмагистраль · транзакции</h2><button id="neftm-export" ${rows.length?'':'disabled'}>Скачать CSV</button></div>
 <form id="neftm-sync" class="toolbar"><label>С<input type="date" name="from" required value="${esc(snap?.from||from)}"></label><label>По<input type="date" name="to" required value="${esc(snap?.to||to)}"></label><button class="primary" ${state.configured?'':'disabled'}>Обновить из Нефтьмагистрали</button></form>
 <p id="neftm-status" role="status">${snap?`Получено ${rows.length} транзакций за ${esc(snap.from)} — ${esc(snap.to)}. Обновлено ${esc(new Date(snap.synced_at).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'}))} МСК.`:state.configured?'Ключ настроен. Выберите период для первой загрузки.':'API-ключ ещё не настроен.'}</p>
 <p class="muted">Обновление выполняется по кнопке за выбранный период. Возвраты показаны отдельно от обслуживания. Держатель карты не считается автомобилем без проверки соответствия; эти операции пока не включены в расчёты рейсов.</p>
 ${snap?table(columns.map(c=>c[1]),rows.map(r=>columns.map(([key])=>esc(key==='typeNumber'?kind(r):key==='dateRec'?new Date(r[key]).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'}):r[key])))):''}`;
 panel.querySelector('#neftm-export').onclick=()=>csv(rows.map(r=>Object.fromEntries(columns.map(([key,label])=>[label,key==='typeNumber'?kind(r):key==='dateRec'?new Date(r[key]).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'}):r[key]]))));
 panel.querySelector('#neftm-sync').onsubmit=async e=>{
  e.preventDefault();const button=e.target.querySelector('button'),status=panel.querySelector('#neftm-status');
  button.disabled=true;status.textContent='Получаем транзакции…';
  try{
   const snapshot=await api('neftm/sync',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});
   if(panel!==$('#neftm-panel'))return;
   drawNeftmPanel(panel,{configured:true,snapshot});
   const sources=await api('connections');if(panel!==$('#neftm-panel'))return;
   const source=sources.find(r=>r.id==='neftm'),card=$('[data-source="neftm"]');
   if(source&&card){card.querySelector('.badge').textContent=source.status;card.querySelector('p').textContent=source.detail}
   toast(`Загружено ${snapshot.rows.length} транзакций`);
  }catch(x){if(panel.isConnected){status.textContent=x.message;status.setAttribute('role','alert');button.disabled=false}}
 };
}


async function loadRosneftPanel(){
 const panel=$('#rosneft-panel');if(!panel)return;
 try{const state=await api('rosneft');if(panel!==$('#rosneft-panel'))return;drawRosneftPanel(panel,state)}
 catch(e){if(panel.isConnected)panel.innerHTML=`<h2>Роснефть · операции</h2><p role="alert">${esc(e.message)}</p>`}
}
function drawRosneftPanel(panel,state){
 const snap=state.snapshot,rows=snap?.rows||[],cards=snap?.cards||[];
 const notes=Object.fromEntries(cards.map(c=>[c.Num,c.Rem]));
 const kind=r=>({1:'Пополнение счёта',4:'Списание со счёта',11:'Обслуживание',24:'Возврат на счёт'}[r.Type]||`Тип ${r.Type}`);
 const localDate=v=>{const [d,t]=String(v).split('T');return d.split('-').reverse().join('.')+(t?' '+t:'')};
 const columns=[['Date','Дата и время терминала'],['Card','Карта'],['note','Примечание карты сейчас'],['GName','Товар / услуга'],['GCat','Категория'],['Value','Количество'],['Price','Цена АЗС'],['Sum','Сумма до скидки'],['DSum','Скидка от суммы'],['NetSum','Сумма после скидки'],['Type','Операция'],['Address','АЗС / адрес'],['Code','ID операции'],['Ref','Исходная операция']];
 const value=(r,key)=>key==='Date'?localDate(r.Date):key==='Type'?kind(r):key==='note'?(notes[r.Card]||''):r[key];
 const fuel=rows.filter(r=>r.GCat==='FUEL'&&[11,24].includes(r.Type));
 const litres=fuel.reduce((sum,r)=>sum+(r.Type===24?-1:1)*Number(r.Value),0);
 const spent=rows.filter(r=>[11,24].includes(r.Type)).reduce((sum,r)=>sum+(r.Type===24?-1:1)*Number(r.NetSum),0);
 panel.innerHTML=`<div class="panel-head"><h2>Роснефть · операции</h2><button id="rosneft-export" ${rows.length?'':'disabled'}>Скачать CSV</button></div>
 <form id="rosneft-sync" class="toolbar"><label>С<input type="date" name="from" required value="${esc(snap?.from||from)}"></label><label>По<input type="date" name="to" required value="${esc(snap?.to||to)}"></label><button class="primary" ${state.configured?'':'disabled'}>Обновить из Роснефти</button></form>
 <p id="rosneft-status" role="status">${snap?`Получено ${rows.length} операций за ${esc(snap.from)} — ${esc(snap.to)}. Обновлено ${esc(new Date(snap.synced_at).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'}))} МСК.`:state.configured?'Доступ настроен. Выберите период для первой загрузки.':'Доступ к API ещё не настроен.'}</p>
 ${snap?`<p>${cards.length} карт · ${rows.filter(r=>r.Type===11).length} операций обслуживания · ${rows.filter(r=>r.Type===24).length} возвратов · Топливо с учётом возвратов: ${esc(litres.toLocaleString('ru-RU',{maximumFractionDigits:3}))} л · Товары и услуги после скидок и возвратов: ${esc(spent.toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2}))} ₽</p>`:''}
 <p class="muted">Период — до 31 дня. Обновление заменяет показанный период. Время операций указано по часовому поясу терминала; поступление данных может задерживаться до двух часов. Количество для услуг может измеряться не в литрах. Примечание карты отражает её текущее назначение; операции пока не включены в расчёты рейсов.</p>
 ${snap?table(columns.map(c=>c[1]),rows.map(r=>columns.map(([key])=>esc(value(r,key))))):''}
 ${snap?`<details><summary>Карты договора (${cards.length})</summary>${table(['Карта','Примечание','Статус','Группа'],cards.map(c=>[c.Num,c.Rem,c.SName,c.CardGrp].map(esc)))}</details>`:''}`;
 panel.querySelector('#rosneft-export').onclick=()=>csv(rows.map(r=>Object.fromEntries(columns.map(([key,label])=>[label,value(r,key)]))));
 panel.querySelector('#rosneft-sync').onsubmit=async e=>{
  e.preventDefault();const button=e.target.querySelector('button'),status=panel.querySelector('#rosneft-status');button.disabled=true;status.textContent='Получаем операции из Роснефти…';
  try{
   const snapshot=await api('rosneft/sync',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});
   if(panel!==$('#rosneft-panel'))return;drawRosneftPanel(panel,{configured:true,snapshot});enhanceTables();
   const sources=await api('connections');if(panel!==$('#rosneft-panel'))return;
   const source=sources.find(r=>r.id==='rosneft'),card=$('[data-source="rosneft"]');
   if(source&&card){card.querySelector('.badge').textContent=source.status;card.querySelector('p').textContent=source.detail}
   toast(`Загружено ${snapshot.rows.length} операций`);
  }catch(x){if(panel.isConnected){status.textContent=x.message;status.setAttribute('role','alert');button.disabled=false}}
 };
}

async function integration(id){
 const target=$('#content');const rows=await api('connections');if(target!==$('#content'))return;
 const source=rows.find(row=>row.id===id);if(!source)throw Error('Источник не найден');
 target.innerHTML=`<p><a href="${pagePath('connections')}">← Все источники данных</a></p>
 ${id==='monitoring'&&U.role==='admin'?'<div class="panel" id="monitoring-history-panel"><p role="status">Загрузка истории…</p></div><div class="panel" id="monitoring-panel"><p role="status">Загрузка объектов…</p></div>':''}
 ${id==='neftm'&&U.role==='admin'?'<div class="panel" id="neftm-panel"><p role="status">Загрузка транзакций…</p></div>':''}
 ${id==='transtrade'&&U.role==='admin'?'<div class="panel" id="transtrade-panel"><p role="status">Загрузка состояния…</p></div>':''}
 ${id==='rosneft'&&U.role==='admin'?'<div class="panel" id="rosneft-panel"><p role="status">Загрузка операций…</p></div>':''}
 <div class="panel"><div class="connection" data-source="${esc(id)}"><div><h2>Состояние подключения</h2><p>${esc(source.detail)}</p>
 <span class="muted">${source.checked_at?'Проверка сети: '+esc(source.checked_at):''}</span>
 ${source.url?`<p><a href="${esc(source.url)}" target="_blank" rel="noreferrer">Документация / кабинет ↗</a></p>`:''}</div><span class="badge">${esc(source.status)}</span></div>
 ${id==='neftm'&&U.role!=='admin'?'<p>Загрузка и просмотр транзакций доступны руководителю.</p>':''}
 ${id==='rosneft'&&U.role!=='admin'?'<p>Загрузка и просмотр операций доступны руководителю.</p>':''}
 ${id==='transtrade'?`<p><a href="${pagePath('orders')}">Открыть заявки →</a></p>`:''}</div>`;
 if(id==='transtrade'&&U.role==='admin')await loadTranstradePanel();
 if(id==='neftm'&&U.role==='admin')await loadNeftmPanel();
 if(id==='rosneft'&&U.role==='admin')await loadRosneftPanel();
 if(id==='monitoring'&&U.role==='admin'){await loadMonitoringPanel();await loadMonitoringHistoryPanel()}
}

async function loadMonitoringPanel(){
 const panel=$('#monitoring-panel');if(!panel)return;
 try{const state=await api('monitoring');if(panel!==$('#monitoring-panel'))return;drawMonitoringPanel(panel,state)}
 catch(e){if(panel.isConnected)panel.innerHTML=`<p role="alert">${esc(e.message)}</p>`}
}
function drawMonitoringPanel(panel,state){
 const snap=state.snapshot,rows=snap?.rows||[],states={0:'Нет данных',1:'Отключён',2:'Остановка',3:'Стоянка',4:'В движении'};
 const date=v=>v?new Date(v).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'}):'Нет данных';
 panel.innerHTML=`<div class="panel-head"><h2>Объекты мониторинга · ${rows.length}</h2><button id="monitoring-sync" class="primary" ${state.configured?'':'disabled'}>Обновить из мониторинга</button></div>
 <p id="monitoring-status" role="status">${snap?`Обновлено ${esc(date(snap.synced_at))} МСК.`:'Данные ещё не загружены.'}</p>
 <p><a href="https://monitoringtransporta.online/client/monitoring" target="_blank" rel="noreferrer">Открыть кабинет мониторинга ↗</a></p>
 <p class="muted">Состояние и скорость — на момент последнего сообщения, указанного в таблице. Старое сообщение не подтверждает текущее состояние автомобиля. Обновление выполняется по кнопке. Исторические пробег, моточасы и расход загружаются в разделе выше и участвуют в статистике и суточной сверке.</p>
 ${table(['Объект','Модель','Состояние по последнему сообщению','Скорость, км/ч','Время сообщения, МСК','Получено сервером, МСК'],rows.map(r=>[esc(r.name),esc(r.modelName),esc(states[r.state]||'Нет данных'),fmt(r.speed),esc(date(r.recordTime)),esc(date(r.receiveTime))]))}`;
 panel.querySelector('#monitoring-sync').onclick=async e=>{
  const button=e.target,status=panel.querySelector('#monitoring-status');button.disabled=true;status.textContent='Получаем объекты и последние показания…';
  try{
   const snapshot=await api('monitoring/sync',{method:'POST',body:'{}'});
   if(panel!==$('#monitoring-panel'))return;
   drawMonitoringPanel(panel,{configured:true,snapshot});
   const sources=await api('connections');if(panel!==$('#monitoring-panel'))return;
   const source=sources.find(r=>r.id==='monitoring'),card=$('[data-source="monitoring"]');
   if(source&&card){card.querySelector('.badge').textContent=source.status;card.querySelector('p').textContent=source.detail}
   toast(`Обновлено ${snapshot.rows.length} объектов`);
  }catch(x){if(panel.isConnected){status.textContent=x.message;status.setAttribute('role','alert');button.disabled=false}}
 };
}

async function loadMonitoringHistoryPanel(){
 const panel=$('#monitoring-history-panel');if(!panel)return;
 try{
  const state=await api('monitoring/history');if(panel!==$('#monitoring-history-panel'))return;
  panel.innerHTML=`<div class="panel-head"><h2>История пробега, моточасов и топлива</h2><a href="${pagePath('reconcile')}">Открыть сверку →</a></div>
  <form id="history-sync" class="toolbar"><label>История с<input type="date" name="from" required value="${esc(state.job?.from||from)}"></label><label>История по<input type="date" name="to" required value="${esc(state.job?.to||to)}"></label><label><input type="checkbox" name="refresh"> Повторно запросить сохранённые дни</label><button class="primary">Загрузить / продолжить</button></form>
  <p id="history-progress" role="status"></p><progress id="history-bar" max="1" value="0" aria-label="Загрузка истории"></progress>
  <p class="muted">Последовательно: одни сутки и до трёх машин на запрос. Полученные порции сохраняются сразу. При перезапуске загрузку можно продолжить. Загружаются только завершённые сутки МСК. Полностью нулевые топливные поля без подтверждённого сигнала отмечаются как отсутствие показаний. Нулевой расход при пробеге больше 1 км отмечается для проверки и исключается из расчёта л/100 км.</p>
  <div id="history-coverage"></div>`;
  const status=panel.querySelector('#history-progress'),button=panel.querySelector('button'),bar=panel.querySelector('#history-bar');
  const update=(state,coverage=true)=>{
   const j=state.job;button.disabled=j?.status==='running';bar.max=j?.total||1;bar.value=j?.done||0;
   status.textContent=j?`${j.from} — ${j.to}: ${j.done} / ${j.total} порций. Ошибок: ${j.failed}. ${j.current&&j.status==='running'?j.current+'. ':''}${j.message}`:'История ещё не загружалась.';
   if(!coverage)return;
   const summary=state.mappings.map(m=>{const rows=state.rows.filter(r=>r.vehicle===m.vehicle);return [esc(m.object),esc(m.vehicle||'—'),esc(m.status),fmt(rows.filter(r=>r.km!=null).length),fmt(rows.filter(r=>r.engine_hours!=null).length),fmt(rows.filter(r=>r.fuel_liters!=null).length),fmt(rows.filter(r=>r.fuel_status!=='pending'&&r.fuel_liters==null).length)]});
   panel.querySelector('#history-coverage').innerHTML=`<h3>Покрытие за весь сохранённый период</h3><p class="muted">Таблица обновляется при открытии страницы и по завершении загрузки; ход загрузки показан выше.</p>${table(['Объект','Автомобиль','Сопоставление','Пробег, дней','Моточасы, дней','Расход, дней','Без топливных показаний, дней'],summary)}`;
  };
  const poll=()=>setTimeout(async()=>{
   if(panel!==$('#monitoring-history-panel'))return;
   try{const state=await api('monitoring/history');if(panel!==$('#monitoring-history-panel'))return;update(state,state.job?.status!=='running');if(state.job?.status==='running')poll();else D=await api('data')}
   catch(e){if(panel.isConnected){status.textContent=e.message;button.disabled=false}}
  },4000);
  update(state);if(state.job?.status==='running')poll();
  panel.querySelector('#history-sync').onsubmit=async e=>{
   e.preventDefault();button.disabled=true;
   const form=new FormData(e.target);
   try{await api('monitoring/history/sync',{method:'POST',body:JSON.stringify({from:form.get('from'),to:form.get('to'),refresh:form.get('refresh')==='on'})});if(panel!==$('#monitoring-history-panel'))return;status.textContent='Загрузка запущена. Можно переходить в другие разделы.';poll()}
   catch(x){if(panel.isConnected){status.textContent=x.message;button.disabled=false}}
  };
 }catch(e){if(panel.isConnected)panel.innerHTML=`<p role="alert">${esc(e.message)}</p>`}
}
