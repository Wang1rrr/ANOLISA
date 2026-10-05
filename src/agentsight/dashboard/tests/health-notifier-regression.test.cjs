const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const test = require('node:test');

const settle = () => new Promise(setImmediate);
const agent = (status, has_crash = false) => ({ pid: 10, agent_name: 'Agent', status, has_crash });

function notifier() {
  const states = [];
  const refs = [];
  const requests = [];
  const intervals = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effects = [];
  const exports = {};
  runInNewContext(readFileSync(process.env.AGENTSIGHT_HEALTH_NOTIFIER_BUILD, 'utf8'), {
    exports,
    setTimeout: () => 0,
    setInterval(callback, ms) { assert.equal(ms, 10_000); intervals.push(callback); return intervals.length; },
    clearInterval() {},
    require(name) {
      if (name === 'react') return {
        useState(initial) {
          const index = stateIndex++;
          if (!(index in states)) states[index] = initial;
          return [states[index], (value) => { states[index] = typeof value === 'function' ? value(states[index]) : value; }];
        },
        useRef(initial) {
          const index = refIndex++;
          return refs[index] ??= { current: initial };
        },
        useEffect: (callback) => effects.push(callback),
        useCallback: (callback) => callback,
      };
      if (name === 'react/jsx-runtime') return {
        jsx: (type, props) => ({ type, props }),
        jsxs: (type, props) => ({ type, props }),
      };
      if (name === '../i18n') return { useI18n: () => ({ t: (key) => key }) };
      if (name === '../utils/apiClient') return {
        fetchAgentProcessHealth(options) {
          assert.equal(options.includeClients, true);
          return new Promise((resolve, reject) => requests.push({ resolve, reject }));
        },
      };
      throw new Error(`Unexpected AgentHealthNotifier dependency: ${name}`);
    },
  });
  function render() {
    stateIndex = 0;
    refIndex = 0;
    effects = [];
    return exports.AgentHealthNotifier();
  }
  return {
    mount() {
      render();
      const cleanup = effects[0]();
      return { cleanup, poll: intervals[intervals.length - 1] };
    },
    requests,
    messages: () => Array.from(render().props.children, (node) => node.props.children),
    async respond(index, agents) { requests[index].resolve({ agents }); await settle(); },
  };
}

test('a never-settling first request cannot prevent later polling snapshots', async () => {
  const view = notifier();
  const effect = view.mount();
  effect.poll();
  assert.equal(view.requests.length, 2);
  await view.respond(1, [agent('healthy')]);
  effect.poll();
  await view.respond(2, [agent('hung')]);
  assert.deepEqual(view.messages(), ['comp.agentHealth.hungToast']);
});

test('slow responses can apply while a newer request is still pending', async () => {
  const view = notifier();
  const effect = view.mount();
  effect.poll();
  await view.respond(0, [agent('hung')]);
  assert.deepEqual(view.messages(), ['comp.agentHealth.hungToast']);
  await view.respond(1, [agent('healthy')]);
  effect.poll();
  await view.respond(2, [agent('hung')]);
  assert.equal(view.messages().length, 2);
});

test('out-of-order responses in the same effect cannot replace a newer applied snapshot', async () => {
  const view = notifier();
  const effect = view.mount();
  effect.poll();
  await view.respond(1, [agent('healthy')]);
  await view.respond(0, [agent('offline', true)]);
  assert.deepEqual(view.messages(), []);
});

test('a replaced effect cannot emit a crash after its successor observes recovery', async () => {
  const view = notifier();
  view.mount().cleanup();
  view.mount();
  await view.respond(1, [agent('healthy')]);
  await view.respond(0, [agent('offline', true)]);
  assert.deepEqual(view.messages(), []);
});

test('effect cleanup invalidates pending responses and queued interval callbacks', async () => {
  const view = notifier();
  const effect = view.mount();
  effect.cleanup();
  effect.poll();
  assert.equal(view.requests.length, 1);
  await view.respond(0, [agent('hung')]);
  assert.deepEqual(view.messages(), []);
});

test('crash notices are deduplicated per episode and can recur after recovery', async () => {
  const view = notifier();
  const effect = view.mount();
  for (const [index, state] of ['offline', 'offline', 'healthy', 'offline'].entries()) {
    if (index) effect.poll();
    await view.respond(index, [agent(state, state === 'offline')]);
  }
  assert.deepEqual(view.messages(), ['comp.agentHealth.crashToast', 'comp.agentHealth.crashToast']);
});

test('obsolete healthy responses cannot reset a current hung notice', async () => {
  const view = notifier();
  view.mount().cleanup();
  const current = view.mount();
  await view.respond(1, [agent('hung')]);
  await view.respond(0, [agent('healthy')]);
  current.poll();
  await view.respond(2, [agent('hung')]);
  assert.deepEqual(view.messages(), ['comp.agentHealth.hungToast']);
});

test('hung notices can recur after recovery or disappearance', async () => {
  const view = notifier();
  const effect = view.mount();
  for (const [index, agents] of [[agent('hung')], [agent('hung')], [agent('healthy')], [agent('hung')], [], [agent('hung')]].entries()) {
    if (index) effect.poll();
    await view.respond(index, agents);
  }
  assert.equal(view.messages().length, 3);
});

test('a failed poll can retry and does not claim a notice before any snapshot', async () => {
  const view = notifier();
  const effect = view.mount();
  view.requests[0].reject(new Error('temporarily unavailable'));
  await settle();
  assert.deepEqual(view.messages(), []);
  effect.poll();
  await view.respond(1, [agent('offline', true)]);
  assert.deepEqual(view.messages(), ['comp.agentHealth.crashToast']);
});
