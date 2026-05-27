import { defineAgent } from '@posthog/ass'

/**
 * Single-turn echo fixture for validating the SDK path against the
 * harness's MockAnthropicServer.
 *
 * Picks `model: "mock-echo"` — the mock's built-in handler returns
 * the latest user message verbatim. No tools, no `ask_for_input`;
 * the agent loop is one assistant response and done. The system
 * prompt is informational only (the mock ignores it).
 *
 * What this test catches:
 *   - `model` propagates from agent.ts through the bundler → manifest
 *     → compileAgent → runSession → SDK options.model.
 *   - The runner subprocess's `ANTHROPIC_BASE_URL` reaches the
 *     SDK and routes to the mock.
 *   - The mock's streaming SSE response is correctly consumed by
 *     the SDK and surfaces as an assistant message.
 *   - The real `AssServerExecutor` → real bundle → real SDK end-to-
 *     end flow against the in-process mock works at all.
 */
export default defineAgent({
    name: 'e2e-mock-echo',
    slug: 'e2e-mock-echo',
    description: 'Echo agent (mock model).',
    model: 'mock-echo',
    prompt: 'You echo the user verbatim. (This prompt is ignored by the mock; left here for parity with real-LLM fixtures.)',
    triggers: [{ id: 'chat', type: 'http_invoke' }],
    tools: [],
    skills: [],
})
