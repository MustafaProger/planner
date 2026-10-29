/* Both Excel planning matrices use the same assignments and stable actions. */
let planRows = 'route';
const plannerWithoutRowChoice = planner;

planCalendar = function(rows) {
 const key = planRows === 'vehicle' ? 'vehicle' : 'route';
 const emptyName = key === 'vehicle' ? 'Не назначен ресурс' : 'Не указан маршрут';
 const groupName = row => row[key] || emptyName;
 const names = [...new Set(rows.map(groupName))].sort((a,b) => a.localeCompare(b,'ru'));
 const days = new Date(+calMonth.slice(0,4),+calMonth.slice(5),0).getDate();
 const heading = key === 'vehicle' ? 'Автомобиль / ресурс' : 'Маршрут';
 return '<div class="table-wrap"><table class="calendar"><thead><tr><th>' + heading + '</th>' +
  Array.from({length:days},(_,i) => `<th>${i+1}</th>`).join('') + '</tr></thead><tbody>' +
  names.map(name => `<tr><td>${esc(name)}</td>` + Array.from({length:days},(_,i) => {
   const day = calMonth + '-' + String(i+1).padStart(2,'0');
   return '<td>' + rows.filter(row => groupName(row) === name && row.date === day).map(row => {
    const counterpart = key === 'vehicle' ? row.route || 'Не указан маршрут' : row.vehicle || 'Не назначен ресурс';
    return `<span class="chip plan">${esc(counterpart)}<br>${esc(row.driver || 'Не назначен водитель')}<br>${esc(stateLabels[row.state] || row.state || 'Назначен')}${row.duplicate_review ? ' · Повтор?' : ''}${recordButtons(row,'plans')}</span>`;
   }).join('') + '</td>';
  }).join('') + '</tr>').join('') + '</tbody></table>' +
  (names.length ? '' : '<div class="empty">За выбранный месяц и фильтры нет назначений.</div>') + '</div>';
};

planner = function() {
 const result = plannerWithoutRowChoice();
 if (planView !== 'calendar') return result;
 const view = $('[name=planView]');
 if (!view) return result;
 view.closest('label').insertAdjacentHTML('afterend',selectField('Строки календаря','planRows',
  selectPairs([['route','Маршруты'],['vehicle','Автомобили']],planRows,null)));
 $('[name=planRows]').onchange = event => {
  planRows = event.target.value === 'vehicle' ? 'vehicle' : 'route';
  planner();
 };
 return result;
};
