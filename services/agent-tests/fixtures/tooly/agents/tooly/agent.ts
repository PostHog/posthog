import { defineAgent } from '@posthog/ass'

/**
 * Tool-using fixture for the agent-tests sandbox e2e suite.
 *
 * The agent has a single locally-defined tool (`magic.summon`) that
 * returns a unique nonce string the model cannot plausibly guess. The
 * system prompt locks the model into "always call the tool, repeat its
 * output verbatim" so the test can prove three things at once:
 *
 *   - the runner extracted the bundle's tool blob (otherwise no
 *     `mcp__ass__magic__summon` would be registered)
 *   - the tool actually executed inside the Docker sandbox (otherwise
 *     the model would have to guess the nonce — extremely unlikely)
 *   - the sandbox lifecycle was tracked durably (the test reads back
 *     a `terminated` row from `agent_stack_agentapplicationsandboxinstance`)
 */
export default defineAgent({
    name: 'e2e-tooly',
    slug: 'e2e-tooly',
    description: 'Tool-using agent — exercises the deployed runner sandbox.',
    prompt: `You are a test agent. Whenever the user sends ANY message your one and only action is:

1. Call the \`magic.summon\` tool with no arguments.
2. Reply with EXACTLY this sentence, substituting the tool's \`word\` field for <word>:
   "The magic word is: <word>"

Do not paraphrase. Do not call any other tool. Do not ask follow-ups. Do not add extra words.`,
    triggers: [{ id: 'chat', type: 'http_invoke' }],
    tools: ['magic'],
    skills: [],
})
