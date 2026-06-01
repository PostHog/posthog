/**
 * `@posthog/load-skill` — fetches a skill's `SKILL.md` body, or a companion
 * file within the skill folder, from the active revision's bundle on demand.
 *
 * The runner builds the system prompt with a one-line index of available
 * skills (`- <id>: <description>`); the model calls this tool only when it
 * actually needs the content. Cheaper than inlining every skill into every
 * prompt. Per the Agent Skills progressive-disclosure model, a `SKILL.md`
 * body can point at companion files under `references/`, `scripts/`,
 * `assets/` (or any nested path); the model loads those on demand by passing
 * `file`.
 *
 * Auto-included by the runner when `spec.skills` is non-empty.
 */

import { defineNativeTool, Type } from '@posthog/agent-shared'

/**
 * Resolve a companion-file path relative to a skill's directory.
 *
 * `skillPath` is the SKILL.md entry path (`skills/<alias>/SKILL.md`); the
 * skill root is its directory. `file` is rejected if it escapes that root
 * (absolute, `..` traversal, or empty segment) — companion files must stay
 * inside the skill folder.
 */
export function resolveSkillFile(skillPath: string, file: string): string {
    const root = skillPath.includes('/') ? skillPath.replace(/\/[^/]*$/, '') : ''
    const rel = file.replace(/\\/g, '/')
    if (rel.startsWith('/')) {
        throw new Error(`load-skill: file "${file}" must be a relative path inside the skill folder.`)
    }
    const segments = rel.split('/')
    if (segments.some((s) => s === '..' || s === '.' || s === '')) {
        throw new Error(`load-skill: file "${file}" must not contain traversal or empty segments.`)
    }
    return root ? `${root}/${rel}` : rel
}

export const loadSkill = defineNativeTool({
    id: '@posthog/load-skill',
    description:
        'Fetch the body of a skill from this agent\'s bundle. Use the `id` from the "Available skills" index in the system prompt. Pass `file` to fetch a companion file inside the skill folder (e.g. `references/api.md`, `scripts/run.py`) when the skill body points at one. Returns the content; treat a skill body as additional instructions for the current task.',
    args: Type.Object({
        id: Type.String({ minLength: 1, description: 'Skill id from the system prompt index.' }),
        file: Type.Optional(
            Type.String({
                minLength: 1,
                description:
                    "Optional companion file path relative to the skill folder. Omit to load the skill's SKILL.md body.",
            })
        ),
    }),
    returns: Type.Object({
        id: Type.String(),
        path: Type.String(),
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
        const path = args.file ? resolveSkillFile(entry.path, args.file) : entry.path
        const body = await ctx.readBundleFile(path)
        if (body === null) {
            throw new Error(`load-skill: skill "${args.id}" path "${path}" not found in the bundle`)
        }
        ctx.log('info', 'skill.loaded', { id: args.id, path, bytes: body.length })
        return { id: args.id, path, body }
    },
})
