const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const test = require('node:test');
const { serializeSavingsCsv } = require(process.env.AGENTSIGHT_SAVINGS_CSV_BUILD);

const session = (id) => ({
  session_id: id, agent_name: 'Example Agent', request_count: 1,
  total_input_tokens: 20, total_output_tokens: 10, total_tokens: 30,
  baseline_tokens: 40, saved_tokens: 10, compounded_saved: 10,
  savings_rate: 0.25, compounded_savings_rate: 0.25, tool_saved: 10,
  mcp_saved: 0, optimization_items: [],
});
const rows = [session('a'), session('b'), session('c')];
const ids = (sessions) => Array.from(sessions, (row) => row.session_id);

function savingsPage() {
  const parentStates = [];
  const rowStates = new Map();
  const refs = [];
  const requests = [];
  const exports = {};
  let states = parentStates;
  let stateIndex = 0;
  let refIndex = 0;
  let downloaded;
  const t = (key, params) => key + (params ? `:${JSON.stringify(params)}` : '');
  runInNewContext(readFileSync(process.env.AGENTSIGHT_SAVINGS_PAGE_BUILD, 'utf8'), {
    exports,
    URLSearchParams,
    require(name) {
      if (name === 'react') return {
        useState(initial) {
          const target = states;
          const index = stateIndex++;
          if (!(index in target)) target[index] = typeof initial === 'function' ? initial() : initial;
          return [target[index], (value) => { target[index] = typeof value === 'function' ? value(target[index]) : value; }];
        },
        useRef(initial) { return refs[refIndex++] ??= { current: initial }; },
        useCallback: (callback) => callback,
        useEffect() {},
      };
      if (name === 'react/jsx-runtime') return {
        jsx: (type, props) => ({ type, props }),
        jsxs: (type, props) => ({ type, props }),
      };
      if (name === 'react-router-dom') return { useSearchParams: () => [new URLSearchParams()] };
      if (name === 'recharts') return {};
      if (name === '../i18n') return { useI18n: () => ({ t }), useLocaleTag: () => 'en-US' };
      if (name === '../components/DateTimePicker') return { DateTimePicker: () => null };
      if (name === '../components/SessionIdHelp') return { SessionIdHelp: () => null };
      if (name === '../utils/savingsCsv') return { downloadSavingsCsv: (sessions) => { downloaded = sessions; } };
      if (name === '../utils/apiClient') return {
        fetchAgentNames: async () => [],
        fetchTokenSavings: () => new Promise((resolve, reject) => requests.push({ resolve, reject })),
      };
      throw new Error(`Unexpected TokenSavingsPage dependency: ${name}`);
    },
  });

  function nodes(node, predicate) {
    if (!node || typeof node !== 'object') return [];
    return [...(predicate(node) ? [node] : []),
      ...[node.props?.children].flat(Infinity).flatMap((child) => nodes(child, predicate))];
  }
  function render() {
    states = parentStates;
    stateIndex = 0;
    refIndex = 0;
    return exports.TokenSavingsPage();
  }
  const buttons = () => nodes(render(), (node) => node.type === 'button');
  const rowElements = () => nodes(render(), (node) => !!node.props?.session);
  function row(id) {
    const element = rowElements().find((node) => node.props.session.session_id === id);
    assert.ok(element, `session ${id} is displayed`);
    if (!rowStates.has(id)) rowStates.set(id, []);
    states = rowStates.get(id);
    stateIndex = 0;
    return element.type(element.props);
  }
  function rowCheckbox(id) {
    return nodes(row(id), (node) => node.type === 'input' && node.props.type === 'checkbox')[0];
  }
  const headerCheckbox = () => nodes(render(), (node) => node.type === 'input' && node.props.type === 'checkbox')[0];
  const exportButton = (selected) => buttons().find((node) => selected
    ? node.props.children.startsWith?.('ts.exportSelectedCsv:')
    : node.props.children === 'ts.exportCsv');
  const query = () => buttons().find((node) => node.props.children === 'common.query').props.onClick();
  return {
    requests,
    query,
    async load(sessions = rows) {
      const result = query();
      requests[requests.length - 1].resolve({ sessions, summary: {}, stats_available: true });
      await result;
    },
    select: (id) => rowCheckbox(id).props.onChange(),
    selectAll: (checked) => headerCheckbox().props.onChange({ target: { checked } }),
    header: headerCheckbox,
    selected: () => rowElements().filter((node) => node.props.selected).map((node) => node.props.session.session_id),
    checkbox: rowCheckbox,
    expand(id) { nodes(row(id), (node) => node.type === 'tr')[0].props.onClick(); },
    expanded: (id) => nodes(row(id), (node) => node.type === 'td' && node.props.colSpan === 7).length > 0,
    button: exportButton,
    export(selected) { exportButton(selected).props.onClick(); return downloaded; },
  };
}

test('individual selection exports only chosen sessions in displayed order without another query', async () => {
  const page = savingsPage();
  assert.equal(page.button(true), undefined);
  await page.load();
  assert.equal(page.button(true).props.disabled, true);
  page.select('c');
  page.select('a');
  assert.deepEqual(Array.from(page.selected()), ['a', 'c']);
  assert.equal(page.button(true).props.children, 'ts.exportSelectedCsv:{"n":2}');
  assert.deepEqual(ids(page.export(true)), ['a', 'c']);
  assert.equal(serializeSavingsCsv(page.export(true)), serializeSavingsCsv([rows[0], rows[2]]));
  assert.deepEqual(ids(page.export(false)), ['a', 'b', 'c']);
  assert.equal(page.requests.length, 1);
  page.select('a');
  assert.deepEqual(ids(page.export(true)), ['c']);
});

test('select-all exposes mixed state and can select or clear the entire snapshot', async () => {
  const page = savingsPage();
  await page.load();
  assert.equal(page.header().props.checked, false);
  page.select('b');
  assert.equal(page.header().props['aria-checked'], 'mixed');
  const domCheckbox = {};
  page.header().props.ref(domCheckbox);
  assert.equal(domCheckbox.indeterminate, true);
  page.selectAll(true);
  assert.equal(page.header().props.checked, true);
  assert.equal(page.header().props['aria-checked'], true);
  assert.deepEqual(ids(page.export(true)), ['a', 'b', 'c']);
  page.selectAll(false);
  assert.equal(page.header().props['aria-checked'], false);
  assert.equal(page.button(true).props.disabled, true);
});

test('a successful replacement query clears selection even for repeated session IDs', async () => {
  const page = savingsPage();
  await page.load();
  page.selectAll(true);
  await page.load([session('a'), session('new')]);
  assert.deepEqual(Array.from(page.selected()), []);
  assert.equal(page.button(true).props.disabled, true);
  assert.deepEqual(ids(page.export(false)), ['a', 'new']);
  assert.equal(page.requests.length, 2);
});

test('querying hides export controls and query errors disable both exports and selection', async () => {
  const page = savingsPage();
  await page.load();
  page.select('a');
  const query = page.query();
  assert.equal(page.button(true), undefined);
  assert.equal(page.button(false), undefined);
  page.requests[1].reject(new Error('failed query'));
  await query;
  assert.equal(page.button(true).props.disabled, true);
  assert.equal(page.button(false).props.disabled, true);
  assert.equal(page.header().props.disabled, true);
  assert.equal(page.checkbox('a').props.disabled, true);
  assert.deepEqual(Array.from(page.selected()), ['a']);
});

test('empty successful snapshots disable select-all and both exports', async () => {
  const page = savingsPage();
  await page.load([]);
  assert.equal(page.header().props.disabled, true);
  assert.equal(page.button(true).props.disabled, true);
  assert.equal(page.button(false).props.disabled, true);
});

test('checkbox clicks preserve expanded details, row identity and accessible session labels', async () => {
  const page = savingsPage();
  await page.load();
  page.expand('b');
  assert.equal(page.expanded('b'), true);
  const checkbox = page.checkbox('b');
  assert.equal(checkbox.props['aria-label'], 'ts.selectSession:{"id":"b"}');
  let stopped = false;
  checkbox.props.onClick({ stopPropagation() { stopped = true; } });
  checkbox.props.onChange();
  assert.equal(stopped, true);
  assert.equal(page.expanded('b'), true);
  assert.equal(page.checkbox('b').props.checked, true);
});
