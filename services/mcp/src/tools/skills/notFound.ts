import { findRecoverableApiError, PostHogApiError } from '@/lib/errors'

import { SKILL_READ_TOOLS } from './analytics'

/** Only the file-level 404 names the enclosing skill, which is how a miss on a
 *  bundled file is told apart from a miss on the skill itself. */
const FILE_MISSING_DETAIL = 'not found in skill'

/** The store's own skill-level 404 detail, from `_skill_not_found_response` in
 *  `products/skills/backend/api/skills.py`. The name lookup is the only thing
 *  that emits it, so a 404 without it came from somewhere else. */
const SKILL_MISSING_DETAIL = 'Skill with name'

/** Which kind of miss the message answers. Stamped on the errored `$mcp_tool_call`
 *  so "agents asking the store for a built-in skill" is its own line in the data,
 *  rather than hiding among the typos in one undifferentiated 404 count. */
export type SkillLookupMissKind = 'builtin' | 'unknown' | 'file' | 'version'

export interface SkillLookupMiss {
    message: string
    kind: SkillLookupMissKind
}

/** What the caller knows about the built-in PostHog skill catalog, which the
 *  store knows nothing about. Optional at every call site, because a connection
 *  that never loaded the catalog cannot claim a name is absent from it. */
export interface BuiltInSkillHint {
    /** True when the name is in the built-in PostHog skill catalog loaded by the server. */
    isBuiltIn: (name: string) => boolean
    /** True when this connection can run `learn posthog:<skill>`. */
    learnAvailable: boolean
}

/**
 * Returns the plain not-found message for a skill lookup 404, or undefined for
 * anything else — a different tool, a different status, or a genuine failure
 * that must keep its own shape.
 *
 * The generic API error shape leads with "Request failed" and an upstream URL,
 * which reads as a service outage rather than a lookup miss. A model that draws
 * that conclusion stops calling the skill tools at all, so the miss has to name
 * itself and point at the tool that lists what exists.
 *
 * Built-in PostHog skills are a separate catalog the store never held, so a tool
 * description that says "load the `<name>` skill" sends an agent to `skill-get`
 * and the store answers 404. Pointing that agent at `skill-list` confirms the
 * wrong conclusion — that the skill does not exist — so a name the built-in
 * catalog knows says where the skill really lives instead.
 */
export function formatSkillLookupMiss(
    toolName: string,
    error: unknown,
    input: Record<string, unknown>,
    hint?: BuiltInSkillHint
): SkillLookupMiss | undefined {
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
        return {
            kind: 'file',
            message: [
                `No file "${filePath}" in the skill "${skillName}".`,
                `Run \`call skill-get {"skill_name": "${skillName}"${pinnedVersion}}\` to see the skill's file manifest.`,
            ].join('\n'),
        }
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
        return {
            kind: 'version',
            message: [
                `No version ${version} of the skill "${skillName}" in this project's skills store. The store answers the same way when the skill itself is missing.`,
                `Run \`call skill-get {"skill_name": "${skillName}"}\` to read the latest version, or \`call skill-list\` to see the skills that are available.`,
            ].join('\n'),
        }
    }

    // A `version` or a `file_path` proves the caller already holds a store skill,
    // so only the bare name lookup can be a built-in skill asked for in the wrong
    // place.
    if (hint?.isBuiltIn(skillName)) {
        return {
            kind: 'builtin',
            message: hint.learnAvailable
                ? [
                      `"${skillName}" is a built-in PostHog skill, not a skill in this project's skills store.`,
                      `Run \`learn posthog:${skillName}\` to load it.`,
                  ].join('\n')
                : [
                      `"${skillName}" is a built-in PostHog skill, not a skill in this project's skills store, and this connection cannot load built-in skills.`,
                      'Use it from your installed PostHog skills if you have them. Otherwise continue with the tool description, which carries the essential steps.',
                  ].join('\n'),
        }
    }

    return {
        kind: 'unknown',
        message: [
            `No skill named "${skillName}" in this project's skills store.`,
            'Run `call skill-list` to see the skills that are available.',
        ].join('\n'),
    }
}
