import { actions, connect, kea, listeners, path, props, reducers } from 'kea'
import api from 'lib/api'

import type { visionHogConfigLogicType } from './visionHogConfiglogicType'
import { visionHogSceneLogic } from './visionHogSceneLogic'

export interface VisionHogConfigLogicProps {
    // Define any props your logic might need here
    // exampleProp?: string
}

export const visionHogConfigLogic = kea<visionHogConfigLogicType>([
    path(['products', 'visionHog', 'frontend', 'visionHogConfigLogic']),
    props({} as VisionHogConfigLogicProps), // Pass empty props object for now

    connect(() => ({
        actions: [visionHogSceneLogic, ['loadStreamConfigs']],
    })),
    actions({
        getConfigSuggestion: (prompt: string) => ({ prompt }),
        setSuggestions: (suggestions: string[]) => ({ suggestions }),
        removeSuggestion: (index: number) => ({ index }),
        updateSuggestion: (index: number, value: string) => ({ index, value }),
        setSuggestionsLoading: (loading: boolean) => ({ loading }),
        addEmptySuggestion: () => ({}),
    }),

    reducers({
        suggestions: [
            [] as string[],
            {
                setSuggestions: (_, { suggestions }) => suggestions,
                removeSuggestion: (state, { index }) => state.filter((_, i) => i !== index),
                updateSuggestion: (state, { index, value }) =>
                    state.map((suggestion, i) => (i === index ? value : suggestion)),
                addEmptySuggestion: (state) => [...state, ''],
            },
        ],
        suggestionsLoading: [false, { setSuggestionsLoading: (_, { loading }) => loading }],
    }),

    listeners(({ values, actions }) => ({
        getConfigSuggestion: async ({ prompt }) => {
            actions.setSuggestionsLoading(true)
            const response = await api.streamConfig.getConfigSuggestion(prompt)
            actions.setSuggestions([...values.suggestions, ...response.suggestions])
            actions.setSuggestionsLoading(false)
        },
        saveStreamConfig: async ({ streamConfig }) => {
            await api.streamConfig.create(streamConfig)
            actions.loadStreamConfigs()
        },
    })),
])
