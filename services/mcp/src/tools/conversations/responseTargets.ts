import type { z } from 'zod'

import { ConversationsResponseTargetsGetSchema, ConversationsResponseTargetsUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

/** One tier of the team's response-target ladder, as stored in
 *  `conversations_settings.response_target_groups`. List order is priority
 *  order (first = highest); tickets matching no group rank with the first. */
export type ResponseTargetGroup = { label: string; tags: string[] }

type GetParams = z.infer<typeof ConversationsResponseTargetsGetSchema>
type UpdateParams = z.infer<typeof ConversationsResponseTargetsUpdateSchema>

type GetResult = {
    customized: boolean
    groups: ResponseTargetGroup[] | null
    message: string
    settings_url: string
}

type UpdateResult = {
    applied: boolean
    groups: ResponseTargetGroup[] | null
    message: string
    settings_url: string
}

/** Coerce the stored value (untyped JSON) into a clean ladder, or null when
 *  absent/malformed — mirroring the backend's read-side fallback, which treats
 *  anything malformed as "use the built-in examples". */
export function normalizeResponseTargetGroups(raw: unknown): ResponseTargetGroup[] | null {
    if (!Array.isArray(raw) || raw.length === 0) {
        return null
    }
    const groups: ResponseTargetGroup[] = []
    for (const entry of raw) {
        const group = (entry ?? {}) as Record<string, unknown>
        if (typeof group.label !== 'string' || !Array.isArray(group.tags)) {
            return null
        }
        if (!group.tags.every((tag) => typeof tag === 'string')) {
            return null
        }
        groups.push({ label: group.label, tags: [...(group.tags as string[])] })
    }
    // The backend also treats duplicate labels as malformed (falls back to the
    // examples), so a dup-label ladder must read as "not customized" here too.
    if (new Set(groups.map((group) => group.label)).size !== groups.length) {
        return null
    }
    return groups
}

/** Fail fast on the mistakes the backend serializer would reject anyway, with
 *  messages actionable enough to fix without a round trip. The server stays
 *  the authority — anything it rejects surfaces as the PATCH error. */
export function validateResponseTargetGroups(groups: ResponseTargetGroup[]): void {
    const seenLabels = new Set<string>()
    const seenTags = new Map<string, string>()
    for (const group of groups) {
        const label = group.label.trim()
        if (seenLabels.has(label)) {
            throw new Error(`Duplicate group label "${label}" — labels must be unique.`)
        }
        seenLabels.add(label)
        for (const rawTag of group.tags) {
            const tag = rawTag.trim()
            const owner = seenTags.get(tag)
            if (owner !== undefined && owner !== label) {
                throw new Error(
                    `Tag "${tag}" is in more than one group ("${owner}" and "${label}") — a tag can only rank one way.`
                )
            }
            seenTags.set(tag, label)
        }
    }
}

function settingsUrl(context: Context, projectId: string): string {
    return `${context.api.getProjectBaseUrl(projectId)}/support/settings#selectedSetting=conversations-response-targets`
}

async function readSavedGroups(context: Context, projectId: string): Promise<ResponseTargetGroup[] | null> {
    const projectResult = await context.api.projects().get({ projectId })
    if (!projectResult.success) {
        throw new Error(`Failed to read conversations settings: ${projectResult.error.message}`)
    }
    const settings = (projectResult.data as { conversations_settings?: Record<string, unknown> | null })
        .conversations_settings
    return normalizeResponseTargetGroups(settings?.response_target_groups)
}

const describeLadder = (groups: ResponseTargetGroup[]): string =>
    groups.map((group, index) => `${index + 1}. ${group.label}`).join(' → ')

export const getResponseTargetsHandler: ToolBase<
    typeof ConversationsResponseTargetsGetSchema,
    GetResult
>['handler'] = async (context: Context, _params: GetParams) => {
    const projectId = await context.stateManager.getProjectId()
    const groups = await readSavedGroups(context, projectId)
    return {
        customized: groups !== null,
        groups,
        message: groups
            ? `The team has a custom ladder of ${groups.length} group(s): ${describeLadder(groups)}. ` +
              'Tickets whose tags match no group rank with the first group.'
            : 'The team has no custom ladder saved and follows the built-in example groups. ' +
              'Save a ladder with conversations-response-targets-update to customize.',
        settings_url: settingsUrl(context, projectId),
    }
}

export const updateResponseTargetsHandler: ToolBase<
    typeof ConversationsResponseTargetsUpdateSchema,
    UpdateResult
>['handler'] = async (context: Context, params: UpdateParams) => {
    const projectId = await context.stateManager.getProjectId()

    if (params.groups) {
        validateResponseTargetGroups(params.groups)
    }
    const current = await readSavedGroups(context, projectId)

    if (!params.confirm) {
        const preview = params.groups
            ? `Would replace the team's ladder (currently ${
                  current ? `${current.length} group(s)` : 'the built-in examples'
              }) with ${params.groups.length} group(s): ${describeLadder(params.groups)}.`
            : 'Would reset the team to the built-in example groups, discarding its custom ladder.'
        return {
            applied: false,
            groups: params.groups ?? null,
            message: `Preview only — nothing saved. ${preview} Re-run with confirm:true to save.`,
            settings_url: settingsUrl(context, projectId),
        }
    }

    const updateResult = await context.api.projects().updateConversationsResponseTargetGroups({
        projectId,
        groups: params.groups ?? null,
    })
    if (!updateResult.success) {
        throw new Error(`Failed to save response target groups: ${updateResult.error.message}`)
    }
    const saved = normalizeResponseTargetGroups(
        (updateResult.data as { conversations_settings?: Record<string, unknown> | null }).conversations_settings
            ?.response_target_groups
    )

    return {
        applied: true,
        groups: saved,
        message: saved
            ? `Saved ${saved.length} group(s): ${describeLadder(saved)}. Sorting the tickets list by ` +
              'Response target now uses this ladder (group first, then SLA within each group).'
            : 'Reset — the team now follows the built-in example groups.',
        settings_url: settingsUrl(context, projectId),
    }
}

export const getResponseTargetsTool = (): ToolBase<typeof ConversationsResponseTargetsGetSchema, GetResult> => ({
    name: 'conversations-response-targets-get',
    schema: ConversationsResponseTargetsGetSchema,
    handler: getResponseTargetsHandler,
})

export const updateResponseTargetsTool = (): ToolBase<
    typeof ConversationsResponseTargetsUpdateSchema,
    UpdateResult
> => ({
    name: 'conversations-response-targets-update',
    schema: ConversationsResponseTargetsUpdateSchema,
    handler: updateResponseTargetsHandler,
})
