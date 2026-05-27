import { defineAgent } from '@posthog/ass'

/**
 * Slow-responding fixture used by tests that need a "turn is running"
 * window — queued follow-ups (mid-turn /send must land durably), worker
 * crashes (kill mid-turn, observe resume), /cancel mid-flight, SSE
 * attach before the assistant message lands.
 *
 * Model: `mock-slow:1500` — the harness's MockAnthropicServer sleeps
 * 1500ms, observes request aborts (so /cancel cuts the sleep short),
 * then echoes the latest user message.
 */
export default defineAgent({
    name: 'e2e-mock-slow',
    slug: 'e2e-mock-slow',
    description: 'Slow echo agent (mock model).',
    model: 'mock-slow:1500',
    prompt: 'You echo the user verbatim, slowly. (Ignored by the mock.)',
    triggers: [{ id: 'chat', type: 'http_invoke' }],
    tools: [],
    skills: [],
})
