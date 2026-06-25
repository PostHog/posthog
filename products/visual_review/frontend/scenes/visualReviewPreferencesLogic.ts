import { actions, kea, path, reducers } from 'kea'

import type { ComparisonMode } from 'lib/components/VisualImageDiffViewer/VisualImageDiffViewer'

import type { visualReviewPreferencesLogicType } from './visualReviewPreferencesLogicType'

export const visualReviewPreferencesLogic = kea<visualReviewPreferencesLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewPreferencesLogic']),
    actions({
        setComparisonMode: (mode: ComparisonMode) => ({ mode }),
        setAddImagesToComment: (enabled: boolean) => ({ enabled }),
    }),
    reducers({
        comparisonMode: [
            'sideBySide' as ComparisonMode,
            { persist: true, prefix: 'visual_review_' },
            {
                setComparisonMode: (_, { mode }) => mode,
            },
        ],
        addImagesToComment: [
            false,
            { persist: true, prefix: 'visual_review_' },
            {
                setAddImagesToComment: (_, { enabled }) => enabled,
            },
        ],
    }),
])
