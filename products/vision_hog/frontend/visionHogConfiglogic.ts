import { actions, kea, listeners, path, props, reducers } from 'kea'
import api from 'lib/api'

import type { visionHogConfigLogicType } from './visionHogConfiglogicType'

export interface VisionHogConfigLogicProps {
    // Define any props your logic might need here
    // exampleProp?: string
}

export const visionHogConfigLogic = kea<visionHogConfigLogicType>([
    path(['products', 'visionHog', 'frontend', 'visionHogConfigLogic']),
    props({} as VisionHogConfigLogicProps), // Pass empty props object for now

    actions({
        // Example: define an action to load data from your temp backend
        // loadTempBackendData: true,
        // setTempBackendData: (data: any) => ({ data }),
        // setTempBackendError: (error: string) => ({ error }),
        getConfigSuggestion: (prompt: string) => ({ prompt }),
        setSuggestions: (suggestions: string[]) => ({ suggestions }),
        removeSuggestion: (index: number) => ({ index }),
        updateSuggestion: (index: number, value: string) => ({ index, value }),
        setSuggestionsLoading: (loading: boolean) => ({ loading }),
        // setVideoUrl: (videoUrl: string) => ({ videoUrl }), // TODO: Uncomment after running kea typegen
    }),

    reducers({
        suggestions: [
            [] as string[],
            {
                setSuggestions: (_, { suggestions }) => suggestions,
                removeSuggestion: (state, { index }) => state.filter((_, i) => i !== index),
                updateSuggestion: (state, { index, value }) =>
                    state.map((suggestion, i) => (i === index ? value : suggestion)),
            },
        ],
        suggestionsLoading: [false, { setSuggestionsLoading: (_, { loading }) => loading }],
        // Example: store data or loading/error states
        // tempBackendData: [null as any | null, { setTempBackendData: (_, { data }) => data }],
        // isLoadingTempBackend: [
        //     false,
        //     {
        //         loadTempBackendData: () => true,
        //         setTempBackendData: () => false,
        //         setTempBackendError: () => false,
        //     },
        // ],
        // tempBackendError: [null as string | null, {
        //     loadTempBackendData: () => null,
        //     setTempBackendError: (_, { error }) => error
        // }]
        // videoUrl: [
        //     '',
        //     {
        //         setVideoUrl: (_, { videoUrl }) => videoUrl,
        //     },
        // ], // TODO: Uncomment after running kea typegen
    }),

    listeners(({ values, actions }) => ({
        getConfigSuggestion: async ({ prompt }) => {
            actions.setSuggestionsLoading(true)
            const response = await api.streamConfig.getConfigSuggestion(prompt)
            actions.setSuggestions([...values.suggestions, ...response.suggestions])
            actions.setSuggestionsLoading(false)
        },
    })),

    // // If you want to load data when the logic is mounted:
    // // afterMount(({ actions }) => {
    // //     actions.loadTempBackendData()
    // // }),
])
