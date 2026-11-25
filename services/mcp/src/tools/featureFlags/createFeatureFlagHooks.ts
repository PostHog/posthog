import type { Schemas } from '@/api/generated'
import { isRecord } from '@/lib/plain-object'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

import { withConditionIds } from './conditionIds'

export const RELEASE_SUGGESTIONS_TIMEOUT_MS = 2000

export const RELEASE_SUGGESTIONS_NOTE =
    'This project groups feature flags into releases, and these existing releases look related to this flag. Ask the ' +
    'user whether to add the flag to one of them; do not add it without asking. To add it, read the release with ' +
    '`release-get`, then call `release-update` with its `feature_flag_ids` plus this flag.'

export const AUTO_RELEASE_NOTE =
    ' In about a minute PostHog puts this flag in a release of its own, unless it is already in one. If that has ' +
    'happened by the time the user answers, merge that release into the chosen one with `release-merge` instead.'

async function fetchFlagReleases(context: Context, flagId: number): Promise<Schemas.FlagReleases> {
    const projectId = await context.stateManager.getProjectId()
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), RELEASE_SUGGESTIONS_TIMEOUT_MS)
    try {
        return await context.api.request<Schemas.FlagReleases>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/releases/flag_suggestions/`,
            query: { feature_flag_id: flagId },
            signal: controller.signal,
        })
    } finally {
        clearTimeout(timer)
    }
}

async function afterResponse(context: Context, _params: unknown, result: unknown): Promise<unknown> {
    const flag = withConditionIds(result)
    if (!isRecord(flag) || typeof flag.id !== 'number') {
        return flag
    }
    const releases = await fetchFlagReleases(context, flag.id).catch(() => null)
    if (!releases || releases.current.length > 0 || releases.suggestions.length === 0) {
        return flag
    }
    return {
        ...flag,
        release_suggestions: releases.suggestions,
        release_suggestions_note: releases.auto_release
            ? RELEASE_SUGGESTIONS_NOTE + AUTO_RELEASE_NOTE
            : RELEASE_SUGGESTIONS_NOTE,
    }
}

export default { afterResponse } satisfies ToolHooks<unknown>
