import { findRecoverableApiError, PostHogApiError } from '@/lib/errors'

/**
 * Rewrites the 404 an agent sees when a skill lookup misses.
 *
 * The generic API error shape leads with "Request failed" and an upstream URL,
 * which reads as a service outage rather than a lookup miss. A model that draws
 * that conclusion stops calling the skill tools at all, so the miss has to name
 * itself and point at the tool that lists what exists.
 */

/** Read tools whose 404 is a lookup miss. Mirrors `SKILL_READ_TOOLS` in
 *  `analytics.ts`, including the `llma-skill-*` deprecated aliases, which reach
 *  this path under their own name. */
const SKILL_LOOKUP_TOOLS = new Set(['skill-get', 'skill-file-get', 'llma-skill-get', 'llma-skill-file-get'])

/** `skill-file-get` misses on either half of the lookup. The API body says
 *  which: only the file-level 404 names the enclosing skill. */
const FILE_MISSING_DETAIL = /not found in skill/

function quoted(value: unknown): string | undefined {
    return typeof value === 'string' && value.length > 0 ? value : undefined
}

/**
 * Returns the plain not-found message for a skill lookup 404, or undefined when
 * the error is anything else — a different tool, a different status, or a
 * genuine failure that must keep its own shape.
 */
export function formatSkillLookupMiss(
    toolName: string,
    error: unknown,
    input: Record<string, unknown>
): string | undefined {
    if (!SKILL_LOOKUP_TOOLS.has(toolName)) {
        return undefined
    }
    const apiError = findRecoverableApiError(error)
    if (!(apiError instanceof PostHogApiError) || apiError.status !== 404) {
        return undefined
    }

    const skillName = quoted(input.skill_name)
    const filePath = quoted(input.file_path)

    if (filePath && FILE_MISSING_DETAIL.test(apiError.body)) {
        return [
            `No file "${filePath}" in the skill "${skillName ?? 'unknown'}".`,
            `Run \`call skill-get {"skill_name": "${skillName ?? '<name>'}"}\` to see the skill's file manifest.`,
        ].join('\n')
    }

    return [
        `No skill named "${skillName ?? 'unknown'}" in this project's skills store.`,
        'Run `call skill-list` to see the skills that are available.',
        'Skills in the repository under .agents/skills are read from disk, not through skill-get.',
    ].join('\n')
}
