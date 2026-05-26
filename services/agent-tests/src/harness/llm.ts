/**
 * Real-LLM gating helper. Opt-in: tests that hit Claude run only when
 * `AGENT_E2E_REAL_LLM=1` is set AND `ANTHROPIC_API_KEY` is present in the
 * env. Otherwise the suite is skipped — CI without a key never bills
 * accidentally, and a developer who forgot `pnpm run :hogli start --intents
 * full` doesn't see a noisy failure.
 *
 * `loadDevEnv()` walks up from cwd to populate `process.env` from the
 * repo-root `.env` first, so the `ANTHROPIC_API_KEY` developers already
 * have set there is found without a separate shell export.
 */
import { loadDevEnv } from '@posthog/agent-core'

loadDevEnv()

export const REAL_LLM = process.env.AGENT_E2E_REAL_LLM === '1' && Boolean(process.env.ANTHROPIC_API_KEY)

export const describeRealLlm: jest.Describe = REAL_LLM ? describe : describe.skip

/**
 * Suggested model for app tests — cheap, fast, deterministic-enough for
 * loose assertions. Tests override per case if they need something larger.
 */
export const DEFAULT_TEST_MODEL = process.env.AGENT_E2E_MODEL ?? 'claude-haiku-4-5'
