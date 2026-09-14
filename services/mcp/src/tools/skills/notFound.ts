import { findRecoverableApiError, PostHogApiError } from '@/lib/errors'

import { SKILL_READ_TOOLS } from './analytics'

/** Only the file-level 404 names the enclosing skill, which is how a miss on a
 *  bundled file is told apart from a miss on the skill itself. */
const FILE_MISSING_DETAIL = 'not found in skill'

/** The store's own skill-level 404 detail, from `_skill_not_found_response` in
 *  `products/skills/backend/api/skills.py`. The name lookup is the only thing
 *  that emits it, so a 404 without it came from somewhere else. */
const SKILL_MISSING_DETAIL = 'Skill with name'

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
    const { skill_name: skillName, file_path: filePath, version } = input
    if (typeof skillName !== 'string' || !skillName) {
        return undefined
    }

    if (typeof filePath === 'string' && filePath && apiError.body.includes(FILE_MISSING_DETAIL)) {
        // A file belongs to one version row, so the manifest worth reading is the
        // one for the version the caller asked for. An unpinned `skill-get`
        // returns the latest version's files, and a publish replaces the whole
        // set, so those paths can be absent at the pinned version.
        const pinnedVersion = typeof version === 'number' ? `, "version": ${version}` : ''
        return [
            `No file "${filePath}" in the skill "${skillName}".`,
            `Run \`call skill-get {"skill_name": "${skillName}"${pinnedVersion}}\` to see the skill's file manifest.`,
        ].join('\n')
    }

    // A 404 the name lookup did not produce says nothing about what the store
    // holds, because it can come from a route or a project the connection cannot
    // reach. Rewriting it would assert the skill is absent on evidence that does
    // not support the claim, so it keeps the generic shape.
    if (!apiError.body.includes(SKILL_MISSING_DETAIL)) {
        return undefined
    }

    // Both read tools take a `version`, and the store returns this same
    // skill-level detail when the name resolves but the pinned version does not
    // exist. So a pinned read cannot be told the skill is absent: `skill-list`
    // would then list the skill the message just denied.
    if (typeof version === 'number') {
        return [
            `No version ${version} of the skill "${skillName}" in this project's skills store. The store answers the same way when the skill itself is missing.`,
            `Run \`call skill-get {"skill_name": "${skillName}"}\` to read the latest version, or \`call skill-list\` to see the skills that are available.`,
        ].join('\n')
    }

    return [
        `No skill named "${skillName}" in this project's skills store.`,
        'Run `call skill-list` to see the skills that are available.',
    ].join('\n')
}
