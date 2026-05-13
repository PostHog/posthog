import { actions, kea, path, reducers } from 'kea'

import type { founderLogicType } from './founderLogicType'

export const founderLogic = kea<founderLogicType>([
    path(['products', 'founder_mode', 'frontend', 'scenes', 'founderLogic']),

    actions({
        setStep: (step: number) => ({ step }),
        // Cross-stage handle. Each stage reads this to know which FounderProject row to read/write.
        // Stage 1 sets it on project create; later stages assume it's already set.
        setCurrentProjectId: (projectId: string | null) => ({ projectId }),
    }),

    reducers({
        step: [
            0,
            {
                setStep: (_, { step }) => step,
            },
        ],
        currentProjectId: [
            null as string | null,
            {
                setCurrentProjectId: (_, { projectId }) => projectId,
            },
        ],
    }),
])
