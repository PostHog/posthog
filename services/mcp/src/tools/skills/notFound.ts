import { findRecoverableApiError, PostHogApiError } from '@/lib/errors'

import { SKILL_READ_TOOLS } from './analytics'

/** Only the file-level 404 names the enclosing skill, which is how a miss on a
 *  bundled file is told apart from a miss on the skill itself. */
const FILE_MISSING_DETAIL = 'not found in skill'

/**
 * Returns the plain not-found message for a skill lookup 404, or undefined for
 * anything else — a different tool, a different status, or a genuine failure
 * that must keep its own shape.
 *
 * The generic API error shape leads with "Request failed" and an upstream URL,
 * which reads as a service outage rather than a lookup miss. A model that draws
 * that conclusion stops calling the skill tools at all, so the miss has to name
 * itself and point at the tool that lists what exists.
 */
export function formatSkillLookupMiss(
    toolName: string,
    error: unknown,
    input: Record<string, unknown>
): string | undefined {
    if (!SKILL_READ_TOOLS.has(toolName)) {
        return undefined
    }
    const apiError = findRecoverableApiError(error)
    if (!(apiError instanceof PostHogApiError) || apiError.status !== 404) {
        return undefined
    }

    // Without the name the caller asked for there is no message worth
    // substituting, so the generic error stands.
    const { skill_name: skillName, file_path: filePath } = input
    if (typeof skillName !== 'string' || !skillName) {
        return undefined
    }

    if (typeof filePath === 'string' && filePath && apiError.body.includes(FILE_MISSING_DETAIL)) {
        return [
            `No file "${filePath}" in the skill "${skillName}".`,
            `Run \`call skill-get {"skill_name": "${skillName}"}\` to see the skill's file manifest.`,
        ].join('\n')
    }

    return [
        `No skill named "${skillName}" in this project's skills store.`,
        'Run `call skill-list` to see the skills that are available.',
        'Skills in the repository under .agents/skills are read from disk, not through skill-get.',
    ].join('\n')
}
