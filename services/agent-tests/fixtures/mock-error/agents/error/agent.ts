import { defineAgent } from '@posthog/ass'

/**
 * Always-failing fixture for the failure-path tests. The mock returns
 * an Anthropic-shaped `overloaded_error` (HTTP 529); the SDK surfaces
 * the error, AssServerExecutor returns `failed`, the worker walks the
 * fail branch.
 */
export default defineAgent({
    name: 'e2e-mock-error',
    slug: 'e2e-mock-error',
    description: 'Always-errors agent (mock model).',
    model: 'mock-error:overloaded',
    prompt: 'You always error. (Prompt ignored by the mock.)',
    triggers: [{ id: 'chat', type: 'http_invoke' }],
    tools: [],
    skills: [],
})
