const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const test = require('node:test');
const rounds = require(process.env.AGENTSIGHT_TRAJECTORY_ROUNDS_BUILD);
const t = (key, params) => `${key}${params ? `:${params.n}` : ''}`;
const step = (step_id, source, other = {}) => ({ step_id, source, ...other });

test('round grouping retains preamble, user ordering and raw step identities', () => {
  const steps = Object.freeze([
    step(1, 'system'), step(2, 'agent'), step(3, 'user'),
    step(4, 'agent'), step(5, 'system'), step(6, 'user'), step(7, 'user'),
  ].map(Object.freeze));
  const before = JSON.stringify(steps);
  const result = rounds.groupIntoRounds(steps, t);
  assert.deepEqual(result.map((round) => round.steps.map((entry) => entry.step_id)), [[1, 2], [3, 4, 5], [6], [7]]);
  assert.deepEqual(result.map((round) => [round.key, round.isPreamble, round.label]), [
    [0, true, 'atif.preamble'], [1, false, 'atif.round:1'], [2, false, 'atif.round:2'], [3, false, 'atif.round:3'],
  ]);
  assert.equal(result[0].userStep, null);
  assert.equal(result[1].userStep, steps[2]);
  for (const [index, item] of result.flatMap((round) => round.steps).entries()) assert.equal(item, steps[index]);
  assert.equal(JSON.stringify(steps), before);
});

test('user-first and agent-only documents preserve their existing round models', () => {
  assert.deepEqual(rounds.groupIntoRounds([], t), []);
  const user = step(10, 'user');
  const first = rounds.groupIntoRounds([user, step(11, 'agent')], t);
  assert.equal(first[0].label, 'atif.round:1');
  assert.equal(first[0].isPreamble, false);
  assert.equal(first[0].userStep, user);
  const agents = rounds.groupIntoRounds([step(12, 'agent'), step(13, 'agent')], t);
  assert.equal(agents.length, 1);
  assert.equal(agents[0].isPreamble, true);
});

test('initial selection prefers the first highlighted round and otherwise the first round', () => {
  const result = rounds.groupIntoRounds([step(1, 'system'), step(10, 'user'), step(11, 'agent'), step(20, 'user')], t);
  assert.equal(rounds.initialRound([], new Set()), null);
  assert.equal(rounds.initialRound(result, new Set()), 0);
  assert.equal(rounds.initialRound(result, new Set(['11-observation'])), 1);
  assert.equal(rounds.initialRound(result, new Set(['20-toolcalls', '11-observation'])), 1);
  assert.equal(rounds.initialRound(result, new Set(['999-toolcalls'])), 0);
});

test('statistics preserve tool/token sums and first source timestamp without mutation', () => {
  const steps = [
    step(1, 'user', { message: '  first\n request  ' }),
    step(2, 'agent', { tool_calls: [{}, {}], timestamp: '2026-10-05T00:00:02Z', metrics: { prompt_tokens: 12, completion_tokens: 3 } }),
    step(3, 'agent', { tool_calls: [{}], timestamp: '2026-10-05T00:00:01Z', metrics: { prompt_tokens: 8, completion_tokens: 0 } }),
    step(4, 'system', { metrics: { completion_tokens: 4 } }),
  ];
  const before = JSON.stringify(steps);
  const result = rounds.roundStats(rounds.groupIntoRounds(steps, t)[0]);
  assert.deepEqual(result, { toolCallCount: 3, promptSum: 20, completionSum: 7, firstTs: '2026-10-05T00:00:02Z', preview: 'first request' });
  assert.equal(JSON.stringify(steps), before);
});

test('preview fallback and an explicitly empty user message keep their existing distinction', () => {
  const preamble = rounds.groupIntoRounds([step(1, 'system'), step(2, 'agent', { message: '  first\tcontent ' })], t)[0];
  assert.equal(rounds.roundStats(preamble).preview, 'first content');
  const user = rounds.groupIntoRounds([step(3, 'user', { message: '' }), step(4, 'agent', { message: 'reply' })], t)[0];
  assert.equal(rounds.roundStats(user).preview, '');
});

test('round labels translate without changing keys, preamble flags or step references', () => {
  const steps = [step(1, 'system'), step(2, 'user')];
  const localized = rounds.groupIntoRounds(steps, (key, params) => `zh:${t(key, params)}`);
  assert.equal(localized[0].label, 'zh:atif.preamble');
  assert.equal(localized[1].label, 'zh:atif.round:1');
  assert.equal(localized[1].key, 1);
  assert.equal(localized[1].userStep, steps[1]);
});

test('the compiled viewer consumes the shared round model for importing and selecting rounds', () => {
  const states = [], refs = [], readers = [];
  let stateIndex = 0, refIndex = 0;
  const exports = {};
  runInNewContext(readFileSync(process.env.AGENTSIGHT_ATIF_PAGE_BUILD, 'utf8'), {
    exports, setTimeout: () => 0,
    FileReader: class { constructor() { readers.push(this); } readAsText() {} },
    require(name) {
      if (name === 'react') return {
        useState(initial) {
          const index = stateIndex++;
          if (!(index in states)) states[index] = typeof initial === 'function' ? initial() : initial;
          return [states[index], (value) => { states[index] = typeof value === 'function' ? value(states[index]) : value; }];
        },
        useRef(initial) { return refs[refIndex++] ??= { current: initial }; },
        useCallback: (callback) => callback, useMemo: (callback) => callback(), useEffect() {},
      };
      if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
      if (name === 'react-router-dom') return { useSearchParams: () => [new URLSearchParams(), () => {}] };
      if (name === '../i18n') return { useI18n: () => ({ t }), useLocaleTag: () => 'en-US' };
      if (name === '../utils/trajectoryRounds') return rounds;
      if (name === '../utils/trajectoryTree') return { buildTrajectoryTree: () => null };
      if (name === '../utils/apiClient' || name.startsWith('../components/')) return {};
      throw new Error(`Unexpected viewer dependency: ${name}`);
    },
  });
  function render() { stateIndex = 0; refIndex = 0; return exports.AtifViewerPage(); }
  function nodes(node, predicate) {
    if (!node || typeof node !== 'object') return [];
    return [...(predicate(node) ? [node] : []), ...[node.props?.children].flat(Infinity).flatMap((child) => nodes(child, predicate))];
  }
  nodes(render(), (node) => node.type === 'input' && node.props.type === 'file')[0].props.onChange({ target: { files: [{}], value: 'file.json' } });
  readers[0].onload({ target: { result: JSON.stringify({ schema_version: 'ATIF-v1.7', session_id: 'fixture', steps: [step(1, 'system'), step(2, 'user'), step(3, 'agent')] }) } });
  const items = nodes(render(), (node) => node.type?.name === 'RoundListItem');
  assert.deepEqual(items.map((item) => item.props.round.key), [0, 1]);
  assert.equal(items[0].props.isActive, true);
  assert.equal(items[1].props.round.label, 'atif.round:1');
  items[1].props.onSelect();
  assert.equal(nodes(render(), (node) => node.type?.name === 'RoundDetail')[0].props.round.key, 1);
});
