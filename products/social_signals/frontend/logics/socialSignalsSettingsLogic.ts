import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import type { socialSignalsSettingsLogicType } from './socialSignalsSettingsLogicType'

export interface MentionSource {
    id: string
    team_id: number
    kind: string
    enabled: boolean
    ingest_token: string
    config: Record<string, unknown>
    created_at: string
    updated_at: string
}

interface SourcesResponse {
    results?: MentionSource[]
}

const OCTOLENS = 'octolens'

export const socialSignalsSettingsLogic = kea<socialSignalsSettingsLogicType>([
    path(['products', 'social_signals', 'frontend', 'logics', 'socialSignalsSettingsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    actions({
        ensureOctolensSource: true,
        rotateToken: true,
        setUpdating: (updating: boolean) => ({ updating }),
    }),
    reducers({
        sourcesUpdating: [false as boolean, { setUpdating: (_, { updating }) => updating }],
    }),
    loaders(({ values }) => ({
        sources: [
            [] as MentionSource[],
            {
                loadSources: async () => {
                    const response = await api.get<SourcesResponse | MentionSource[]>(
                        `api/projects/${values.currentProjectId}/social_signals/sources/`
                    )
                    if (Array.isArray(response)) {
                        return response
                    }
                    return response.results ?? []
                },
                _setSources: (next: MentionSource[]) => next,
            },
        ],
    })),
    listeners(({ values, actions }) => ({
        ensureOctolensSource: async () => {
            if (values.sourcesUpdating) {
                return
            }
            actions.setUpdating(true)
            try {
                const created = await api.create<MentionSource>(
                    `api/projects/${values.currentProjectId}/social_signals/sources/`,
                    { kind: OCTOLENS }
                )
                actions._setSources(
                    values.sources.some((s) => s.id === created.id)
                        ? values.sources.map((s) => (s.id === created.id ? created : s))
                        : [...values.sources, created]
                )
            } finally {
                actions.setUpdating(false)
            }
        },
        rotateToken: async () => {
            const current = values.octolensSource
            if (!current || values.sourcesUpdating) {
                return
            }
            actions.setUpdating(true)
            try {
                const rotated = await api.create<MentionSource>(
                    `api/projects/${values.currentProjectId}/social_signals/sources/${current.id}/rotate_token/`,
                    {}
                )
                actions._setSources(values.sources.map((s) => (s.id === rotated.id ? rotated : s)))
            } finally {
                actions.setUpdating(false)
            }
        },
    })),
    selectors({
        octolensSource: [
            (s) => [s.sources],
            (sources: MentionSource[]): MentionSource | null =>
                sources.find((s) => s.kind === OCTOLENS) ?? null,
        ],
        webhookUrl: [
            (s) => [s.octolensSource],
            (source: MentionSource | null): string => {
                if (!source) {
                    return ''
                }
                const origin = typeof window !== 'undefined' ? window.location.origin : ''
                return `${origin}/api/social_signals/webhook/${source.ingest_token}/`
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                { key: 'social_signals', name: 'Social signals' },
                { key: 'social_signals_settings', name: 'Settings' },
            ],
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadSources()
    }),
])
