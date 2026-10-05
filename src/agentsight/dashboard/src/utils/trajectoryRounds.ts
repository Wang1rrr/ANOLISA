import type { AtifStep } from '../types';
import type { MessageKey } from '../i18n';

// ─── Round grouping ───────────────────────────────────────────────────────────
// A "round" starts at each user step and spans the following agent/system steps,
// mirroring the round-based trajectory view in agentopt.

export interface Round {
  key: number;
  label: string;
  /** True for the synthetic leading round that only carries the system prompt.
   *  Kept separate from `label` so consumers never branch on translated text. */
  isPreamble: boolean;
  userStep: AtifStep | null;
  steps: AtifStep[];
}

/** Group user turns and an optional leading preamble without changing steps. */
export function groupIntoRounds(steps: AtifStep[], t: (key: MessageKey, params?: Record<string, string | number>) => string): Round[] {
  const rounds: Round[] = [];
  let userRoundCount = 0;
  for (const step of steps) {
    if (step.source === 'user' || rounds.length === 0) {
      const isUser = step.source === 'user';
      if (isUser) userRoundCount++;
      rounds.push({
        key: rounds.length,
        label: isUser ? t('atif.round', { n: userRoundCount }) : t('atif.preamble'),
        isPreamble: !isUser,
        userStep: isUser ? step : null,
        steps: [step],
      });
    } else {
      rounds[rounds.length - 1].steps.push(step);
    }
  }
  return rounds;
}

/** Round to auto-select: prefer the highlighted round, else the first round. */
export function initialRound(rounds: Round[], sections: Set<string>): number | null {
  if (rounds.length === 0) return null;
  if (sections.size > 0) {
    const stepIds = new Set<number>();
    sections.forEach(k => stepIds.add(parseInt(k, 10)));
    for (const round of rounds) {
      if (round.steps.some(s => stepIds.has(s.step_id))) return round.key;
    }
  }
  return rounds[0].key;
}

export interface RoundStats {
  toolCallCount: number;
  promptSum: number;
  completionSum: number;
  firstTs?: string;
  preview: string;
}

/** Summarize a round using the same raw metric and preview fields as the viewer. */
export function roundStats(round: Round): RoundStats {
  let toolCallCount = 0, promptSum = 0, completionSum = 0;
  for (const s of round.steps) {
    toolCallCount += (Array.isArray(s.tool_calls) ? s.tool_calls.length : 0);
    promptSum += s.metrics?.prompt_tokens ?? 0;
    completionSum += s.metrics?.completion_tokens ?? 0;
  }
  const preview = (round.userStep?.message ?? round.steps.find(s => s.message)?.message ?? '')
    .replace(/\s+/g, ' ')
    .trim();
  return { toolCallCount, promptSum, completionSum, firstTs: round.steps.find(s => s.timestamp)?.timestamp, preview };
}
