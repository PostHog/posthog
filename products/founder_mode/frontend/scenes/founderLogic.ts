import { actions, kea, path, reducers } from 'kea'

import type { founderLogicType } from './founderLogicType'

export const founderLogic = kea<founderLogicType>([
    path(['products', 'founder_mode', 'frontend', 'scenes', 'founderLogic']),

    actions({
        setStep: (step: number) => ({ step }),
    }),

    reducers({
        step: [
            0,
            {
                setStep: (_, { step }) => step,
            },
        ],
    }),
])
