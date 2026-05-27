import { defineAgent } from '@posthog/ass'

/**
 * Webhook-calling fixture for the secret-broker e2e suite.
 *
 * The point of this agent is to exercise `SecretBroker` end-to-end: the
 * tool requests `ctx.secrets.ref('WEBHOOK_URL')` (gets a `{{secret:...}}`
 * nonce, never the URL), passes the nonce to `ctx.http.fetch`, and the
 * sandbox's egress proxy substitutes the real URL at the last hop. The
 * test asserts (a) the webhook tester received the request — substitution
 * worked — and (b) the URL never appears in any log entry — the nonce did
 * its job.
 */
export default defineAgent({
    name: 'e2e-wired',
    slug: 'e2e-wired',
    description: 'Webhook-calling agent — exercises the SecretBroker substitution.',
    prompt: `You are a test agent. Whenever the user sends ANY message your one and only action is:

1. Call the \`hook.deliver\` tool with title="ping" and body="e2e".
2. Reply with EXACTLY this sentence, substituting the tool's \`status\` field for <status>:
   "delivery status: <status>"

Do not paraphrase. Do not call any other tool. Do not add extra words.`,
    triggers: [{ id: 'chat', type: 'http_invoke' }],
    tools: ['hook'],
    skills: [],
})
