import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import type { socialSignalsLogicType } from './socialSignalsLogicType'

export interface MentionAnalysis {
    id: string
    mention_id: string
    kind: string
    status: string
    result: Record<string, unknown>
    model_used: string
    error: string
    created_at: string
    updated_at: string
}

export interface Mention {
    id: string
    team_id: number
    source_id: string
    platform: string
    mention_type: string
    external_id: string
    url: string
    content: string
    language: string
    author_handle: string
    author_display_name: string
    author_profile_url: string
    author_followers: number | null
    posted_at: string | null
    captured_at: string
    engagement: Record<string, unknown>
    status: string
    last_error: string
    updated_at: string
    analyses: MentionAnalysis[]
}

interface MentionsResponse {
    results?: Mention[]
}

// Mentions list scene logic. Loads the team's mentions on mount.
// Generated API types will replace these hand-rolled interfaces once
// `hogli build:openapi` is run for this product.
export const socialSignalsLogic = kea<socialSignalsLogicType>([
    path(['products', 'social_signals', 'frontend', 'logics', 'socialSignalsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    loaders(({ values }) => ({
        mentions: [
            [] as Mention[],
            {
                loadMentions: async () => {
                    const response = await api.get<MentionsResponse | Mention[]>(
                        `api/projects/${values.currentProjectId}/social_signals/mentions/`
                    )
                    if (Array.isArray(response)) {
                        return response
                    }
                    return response.results ?? []
                },
            },
        ],
    })),
    selectors({
        breadcrumbs: [() => [], (): Breadcrumb[] => [{ key: 'social_signals', name: 'Social signals' }]],
    }),
    afterMount(({ actions }) => {
        actions.loadMentions()
    }),
])
