import { actions, kea, listeners, path, props, reducers } from 'kea'
import api from 'lib/api'

import { visionHogConfigLogicType } from './visionHogConfiglogicType'

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
        getConfigSuggestion: true,
    }),

    reducers({
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
    }),

    listeners(() => ({
        getConfigSuggestion: async () => {
            await api.streamConfig.getConfigSuggestion()
        },
    })),

    // // If you want to load data when the logic is mounted:
    // // afterMount(({ actions }) => {
    // //     actions.loadTempBackendData()
    // // }),
])
