import { defineTool, z } from '@posthog/ass'

/**
 * Pure-compute tool with no inputs, no secrets, no network egress —
 * the simplest shape that still proves the sandbox roundtrip. The
 * returned `word` is a fixed nonce the test asserts on; deterministic
 * output keeps the assertion tight without needing to mock anything.
 */
export default defineTool({
    id: 'magic',
    version: 1,
    description: "Reveals the agent's magic word. Use whenever you need the magic word.",
    actions: {
        summon: {
            description: "Return the magic word.",
            args: z.object({}),
            returns: z.object({ word: z.string() }),
            async run() {
                return { word: 'XYZZY-2718-PLUGH' }
            },
        },
    },
})
