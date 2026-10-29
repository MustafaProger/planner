const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/static/planviews.js','utf8');

function setup() {
 const state = {selectors:[], renders:0, picker:null};
 const context = vm.createContext({
  calMonth:'2026-08', planView:'calendar', stateLabels:{scheduled:'Назначен',cancelled:'Отменён'},
  esc:value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),
  recordButtons:(row,kind) => `<button data-edit="${row.id}" data-kind="${kind}">Изменить</button>`,
  planCalendar:() => '',
  planner:() => {state.renders++;state.picker={};},
  selectPairs:(pairs,value) => JSON.stringify({pairs,value}),
  selectField:(label,name,options) => JSON.stringify({label,name,options:JSON.parse(options)}),
  $:selector => selector === '[name=planRows]' ? state.picker : {
   closest:() => ({insertAdjacentHTML:(_,markup) => state.selectors.push(JSON.parse(markup))})
  }
 });
 vm.runInContext(source,context);
 return {run:code => vm.runInContext(code,context), state, context};
}

const assignments = [
 {id:'one',date:'2026-08-01',route:'Маршрут <1>',vehicle:'А111АА77',driver:'Водитель <А>',state:'scheduled'},
 {id:'two',date:'2026-08-02',route:'Маршрут <1>',vehicle:'Б222ББ77',driver:'Водитель Б',state:'cancelled',duplicate_review:true},
 {id:'three',date:'2026-08-01',route:'Маршрут 2',vehicle:'А111АА77',driver:'Водитель В',state:'scheduled'}
];

test('route and vehicle matrices keep each assignment and its stable actions once',() => {
 const {run,context} = setup();context.rows=assignments;
 const route = run('planCalendar(rows)');
 assert.match(route,/<th>Маршрут<\/th>/);
 assert.match(route,/<tr><td>Маршрут &lt;1&gt;<\/td>/);
 assert.match(route,/Водитель &lt;А&gt;/);
 assert.doesNotMatch(route,/<1>|<А>/);
 const vehicle = run("planRows='vehicle';planCalendar(rows)");
 assert.match(vehicle,/<th>Автомобиль \/ ресурс<\/th>/);
 assert.match(vehicle,/<tr><td>А111АА77<\/td>/);
 assert.match(vehicle,/<tr><td>Б222ББ77<\/td>/);
 assert.match(vehicle,/Маршрут &lt;1&gt;/);
 for(const html of [route,vehicle]) {
  for(const row of assignments) assert.equal(html.split(`data-edit="${row.id}"`).length-1,1);
  assert.match(html,/Отменён · Повтор\?/);
  assert.equal((html.match(/<tr><td>/g)||[]).length,2);
 }
});

test('row selection survives planner rerenders and list/calendar switching',() => {
 const {run,state} = setup();run('planner()');
 assert.equal(state.selectors.at(-1).options.value,'route');
 state.picker.onchange({target:{value:'vehicle'}});
 assert.equal(run('planRows'),'vehicle');
 assert.equal(state.selectors.at(-1).options.value,'vehicle');
 run('planner()');assert.equal(state.selectors.at(-1).options.value,'vehicle');
 const prior=state.selectors.length;
 run("planView='list';planner()");assert.equal(state.selectors.length,prior);
 run("planView='calendar';planner()");assert.equal(state.selectors.at(-1).options.value,'vehicle');
});

test('empty calendars explain absence and incomplete assignments remain visible',() => {
 const {run,context} = setup();
 assert.match(run('planCalendar([])'),/нет назначений/);
 context.rows=[{id:'missing',date:'2026-08-01',route:'',vehicle:'',driver:'',state:'scheduled'}];
 const html=run("planRows='vehicle';planCalendar(rows)");
 assert.match(html,/Не назначен ресурс/);assert.match(html,/Не указан маршрут/);assert.match(html,/Не назначен водитель/);
 assert.match(html,/data-edit="missing"/);
});
