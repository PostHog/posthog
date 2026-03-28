import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { llmTaggersLogicType } from './llmTaggersLogicType'
import { defaultTaggerTemplates } from './templates'
import { Tagger } from './types'

export interface LLMTaggersLogicProps {
    tabId?: string
}

export const llmTaggersLogic = kea<llmTaggersLogicType>([
    path(['products', 'llm_analytics', 'taggers', 'llmTaggersLogic']),
    props({} as LLMTaggersLogicProps),
    key((props) => props.tabId ?? 'default'),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [teamLogic, ['addProductIntent']],
    })),

    actions({
        loadTaggers: true,
        loadTaggersSuccess: (taggers: Tagger[]) => ({ taggers }),
        toggleTaggerEnabled: (id: string) => ({ id }),
        setTaggersFilter: (filter: string) => ({ filter }),
    }),

    reducers({
        taggers: [
            [] as Tagger[],
            {
                loadTaggersSuccess: (_, { taggers }) => taggers,
            },
        ],
        taggersLoading: [
            false,
            {
                loadTaggers: () => true,
                loadTaggersSuccess: () => false,
            },
        ],
        taggersFilter: [
            '',
            {
                setTaggersFilter: (_, { filter }) => filter,
            },
        ],
    }),

    selectors({
        filteredTaggers: [
            (s) => [s.taggers, s.taggersFilter],
            (taggers: Tagger[], filter: string): Tagger[] => {
                if (!filter) {
                    return taggers
                }
                const lowerFilter = filter.toLowerCase()
                return taggers.filter(
                    (tagger) =>
                        tagger.name.toLowerCase().includes(lowerFilter) ||
                        tagger.description?.toLowerCase().includes(lowerFilter) ||
                        tagger.tagger_config.tags.some((tag) => tag.name.toLowerCase().includes(lowerFilter))
                )
            },
        ],
    }),

    listeners(({ actions }) => ({
        loadTaggers: async () => {
            const response = await api.get('api/environments/@current/taggers/')
            if (response.results.length === 0) {
                // Seed default taggers on first visit
                for (const template of defaultTaggerTemplates) {
                    await api.create('api/environments/@current/taggers/', {
                        name: template.name,
                        description: template.description,
                        enabled: false,
                        tagger_config: template.tagger_config,
                        conditions: [{ id: `cond-${Date.now()}`, rollout_percentage: 100, properties: [] }],
                    })
                }
                const seeded = await api.get('api/environments/@current/taggers/')
                actions.loadTaggersSuccess(seeded.results)
            } else {
                actions.loadTaggersSuccess(response.results)
            }
        },
        toggleTaggerEnabled: async ({ id }, breakpoint) => {
            const response = await api.get(`api/environments/@current/taggers/${id}/`)
            await api.update(`api/environments/@current/taggers/${id}/`, { enabled: !response.enabled })
            await breakpoint(100)
            actions.loadTaggers()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTaggers()
    }),
])
