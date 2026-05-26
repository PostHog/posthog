import { defineAgent } from '@posthog/ass'

/**
 * Minimal multi-turn agent for the agent-tests e2e suite.
 *
 * Uses ass-server's built-in `ask_for_input` meta-tool to pause the
 * session between turns — POST /send/:id delivers the user's name and
 * resumes the run. No custom tools; the system prompt locks the model
 * into a deterministic two-step flow so loose-string assertions in the
 * test can be tight.
 */
export default defineAgent({
    name: 'e2e-greeter',
    slug: 'e2e-greeter',
    description: 'Two-turn greeting agent used by services/agent-tests app tests.',
    prompt: `You are a polite greeting bot used in an automated test suite.

Strict two-step flow:
1. First, call the \`ask_for_input\` tool with the exact prompt
   "What's your name?" — do not emit any free-text before calling it.
2. The tool returns the user's reply. Treat its entire content as the
   user's name. End your run by replying with EXACTLY one sentence:
   "Hello <name>, welcome!" — substitute the user's exact text for
   <name>.

Never use any other tools. Never elaborate. Stay on-script.`,
    triggers: [{ id: 'chat', type: 'http_invoke' }],
    tools: [],
    skills: [],
})
