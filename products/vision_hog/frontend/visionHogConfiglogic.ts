import { actions, connect, events, kea, listeners, path, props, reducers, selectors } from 'kea'
import api from 'lib/api'

import type { visionHogConfigLogicType } from './visionHogConfiglogicType'
import { visionHogSceneLogic } from './visionHogSceneLogic'

export interface VisionHogConfigLogicProps {
    // Define any props your logic might need here
    // exampleProp?: string
}

export enum ConfigState {
    CREATE = 'create',
    EDIT = 'edit',
}

export const visionHogConfigLogic = kea<visionHogConfigLogicType>([
    path(['products', 'visionHog', 'frontend', 'visionHogConfigLogic']),
    props({} as VisionHogConfigLogicProps), // Pass empty props object for now

    connect(() => ({
        values: [visionHogSceneLogic, ['targetStreamConfig']],
        actions: [visionHogSceneLogic, ['loadStreamConfigs', 'setActiveTab']],
    })),
    actions({
        getConfigSuggestion: (prompt: string) => ({ prompt }),
        setSuggestions: (suggestions: string[]) => ({ suggestions }),
        removeSuggestion: (index: number) => ({ index }),
        updateSuggestion: (index: number, value: string) => ({ index, value }),
        setSuggestionsLoading: (loading: boolean) => ({ loading }),
        addEmptySuggestion: () => ({}),
        setUrl: (url: string) => ({ url }),
        saveStreamConfig: true,
    }),

    reducers({
        url: ['', { setUrl: (_, { url }) => url }],
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
        saveStreamConfig: async () => {
            if (values.configState === ConfigState.CREATE) {
                await api.streamConfig.create({
                    stream_url: values.url,
                    events: values.suggestions,
                })
            } else {
                await api.streamConfig.update(values.targetStreamConfig.id, {
                    stream_url: values.url,
                    events: values.suggestions,
                })
            }
            actions.setActiveTab('video')
            actions.loadStreamConfigs()
        },
    })),
    selectors({
        configState: [
            (s) => [s.targetStreamConfig],
            (targetStreamConfig) =>
                targetStreamConfig && targetStreamConfig.id ? ConfigState.EDIT : ConfigState.CREATE,
        ],
    }),
    events(({ values, actions }) => ({
        afterMount() {
            if (values.targetStreamConfig) {
                actions.setUrl(values.targetStreamConfig.stream_url)
                actions.setSuggestions(values.targetStreamConfig.events)
            }
        },
    })),
])
