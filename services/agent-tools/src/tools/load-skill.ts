/**
 * `@posthog/load-skill` — fetches a skill body from the active revision's
 * bundle on demand. The runner builds the system prompt with a one-line
 * index of available skills (`- <id>: <description>`); the model calls this
 * tool only when it actually needs the body. Cheaper than inlining every
 * skill into every prompt.
 *
 * Auto-included by the runner when `spec.skills` is non-empty.
 */

import { defineNativeTool, Type } from '@posthog/agent-shared-v2'

export const loadSkill = defineNativeTool({
    id: '@posthog/load-skill',
    description:
        'Fetch the body of a skill from this agent\'s bundle. Use the `id` from the "Available skills" index in the system prompt. Returns the markdown content; treat it as additional instructions for the current task.',
    args: Type.Object({
        id: Type.String({ minLength: 1, description: 'Skill id from the system prompt index.' }),
    }),
    returns: Type.Object({
        id: Type.String(),
        body: Type.String(),
    }),
    requires: { integrations: [], scopes: [] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        if (!ctx.skillIndex || !ctx.readBundleFile) {
            throw new Error('load-skill: runner did not wire skill access (skillIndex/readBundleFile)')
        }
        const entry = ctx.skillIndex.find((s) => s.id === args.id)
        if (!entry) {
            throw new Error(
                `load-skill: unknown skill id "${args.id}". Available: ${ctx.skillIndex.map((s) => s.id).join(', ') || '(none)'}`
            )
        }
        const body = await ctx.readBundleFile(entry.path)
        if (body === null) {
            throw new Error(`load-skill: skill "${args.id}" path "${entry.path}" not found in the bundle`)
        }
        ctx.log('info', 'skill.loaded', { id: args.id, bytes: body.length })
        return { id: args.id, body }
    },
})
