import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { studyDetailsSceneLogicType } from './studyDetailsSceneLogicType'
import { Study } from './types'

export interface StudyDetailsSceneLogicProps {
    id: string
}

export const studyDetailsSceneLogic = kea<studyDetailsSceneLogicType>([
    props({} as StudyDetailsSceneLogicProps),
    key(({ id }) => id),
    path((id) => ['products', 'synthetic-users', 'frontend', 'studyDetailsSceneLogic', id]),

    loaders(({ props }) => ({
        study: [
            null as Study | null,
            {
                loadStudy: async () => {
                    const response = await api.syntheticUsers.getStudy(props.id)
                    return response.study
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadStudy()
    }),
])
