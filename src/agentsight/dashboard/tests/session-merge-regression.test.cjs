const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const test = require('node:test');

const exportsObject = {};
runInNewContext(readFileSync(process.env.AGENTSIGHT_SESSION_PAGE_BUILD, 'utf8'), {
  exports: exportsObject,
  require: () => ({}),
});
const mergeSessions = (ebpf, logs) => JSON.parse(JSON.stringify(exportsObject.mergeSessions(ebpf, logs)));

const uuid = '00000000-0000-0000-0000-000000000001';
const rollout = `rollout-2026-10-01T00-00-00-${uuid}`;
const captured = (session_id = uuid) => ({
  session_id, agent_name: 'codex', model: 'captured-model', conversation_count: 3,
  total_input_tokens: 20, total_output_tokens: 10, first_user_query: 'captured', last_seen_ns: 1_000_000,
});
const trajectory = (session_id, extra = {}) => ({
  session_id, agent_name: 'codex', model_name: 'log-model', project: '/example/project', num_steps: 7,
  total_prompt_tokens: 40, total_completion_tokens: 30, collected_at_ns: 2_000_000,
  first_user_message: 'log preview', is_subagent: false, ...extra,
});
const children = (parent) => [1, 2].map((id) => trajectory(`${parent}:subagent:child-${id}`, { is_subagent: true }));

test('Codex aliases merge their child count into the captured parent row', () => {
  const ebpf = [captured()];
  const logs = [trajectory(rollout), ...children(rollout)];
  const before = JSON.stringify({ ebpf, logs });
  const result = mergeSessions(ebpf, logs);
  assert.equal(result.length, 1);
  assert.deepEqual(result[0], {
    session_id: uuid, sources: ['ebpf', 'log'], agent_name: 'codex', project: '/example/project',
    model: 'captured-model', count: 3, input_tokens: 20, output_tokens: 10,
    first_message: 'log preview', last_message: null, last_active_ms: 2, subagent_count: 2,
  });
  assert.equal(JSON.stringify({ ebpf, logs }), before);
});

test('matching IDs do not count the same children twice while merging sources', () => {
  const result = mergeSessions([captured()], [trajectory(uuid), ...children(uuid)]);
  assert.equal(result.length, 1);
  assert.equal(result[0].subagent_count, 2);
  assert.deepEqual(result[0].sources, ['ebpf', 'log']);
});

test('alias child counts survive logs arriving before the parent trajectory', () => {
  const result = mergeSessions([captured()], [...children(rollout), trajectory(rollout)]);
  assert.equal(result.length, 1);
  assert.equal(result[0].subagent_count, 2);
});

test('log-only parents still own their children regardless of log order', () => {
  const result = mergeSessions([], [...children(rollout), trajectory(rollout)]);
  assert.equal(result.length, 1);
  assert.equal(result[0].session_id, rollout);
  assert.equal(result[0].subagent_count, 2);
  assert.equal(result[0].input_tokens, 40);
});

test('orphaned children remain visible and unrelated parents retain zero children', () => {
  const result = mergeSessions([captured()], children('other-parent'));
  assert.equal(result.length, 3);
  assert.equal(result.find((row) => row.session_id === uuid).subagent_count, 0);
  assert.equal(result.filter((row) => row.session_id.startsWith('other-parent:subagent:')).length, 2);
  assert.equal(mergeSessions([captured()], [trajectory(rollout)])[0].subagent_count, 0);
});
