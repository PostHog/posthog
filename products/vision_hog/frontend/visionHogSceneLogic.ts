import { actions, kea, path, props, reducers, selectors } from 'kea'
import api from 'lib/api'
// import api from 'lib/api' // Your project's API utility if you have one
import { loaders } from 'node_modules/kea-loaders/lib'

import { StreamConfig } from '~/types'

import type { visionHogSceneLogicType } from './visionHogSceneLogicType'

export interface VisionHogSceneLogicProps {
    // Define any props your logic might need here
    // exampleProp?: string
}

export const visionHogSceneLogic = kea<visionHogSceneLogicType>([
    path(['products', 'visionHog', 'frontend', 'visionHogSceneLogic']),
    props({} as VisionHogSceneLogicProps), // Pass empty props object for now

    actions({
        setVideoUrl: (url: string) => ({ url }),
    }),

    loaders({
        streamConfigs: [
            [] as StreamConfig[],
            {
                loadStreamConfigs: async () => {
                    const response = await api.streamConfig.list()
                    return response.results
                },
            },
        ],
    }),

    reducers({
        videoUrl: [
            '',
            {
                setVideoUrl: (_, { url }) => url,
            },
        ],
    }),
    selectors({
        targetStreamConfig: [
            (s) => [s.streamConfigs],
            (streamConfigs) => (streamConfigs.length > 0 ? streamConfigs[0] : null),
        ],
    }),
])
