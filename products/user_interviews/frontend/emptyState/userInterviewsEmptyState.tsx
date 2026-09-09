import * as reporterPng from '@posthog/brand/hoggies/png/reporter'
import { IconMicrophone } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import { NewTopicButton } from './NewTopicButton'
import { UserInterviewPreview } from './UserInterviewPreview'
import { userInterviewsSetupLogic } from './userInterviewsSetupLogic'

const HedgehogReporter = pngHoggie(reporterPng)

export const userInterviewsEmptyState: SceneProductEmptyState = {
    statusLogic: userInterviewsSetupLogic,
    // The whole product is behind this flag (nav-gated); flag-off users never reach the scene.
    featureFlag: FEATURE_FLAGS.USER_INTERVIEWS,
    config: {
        productKey: ProductKey.USER_INTERVIEWS,
        productName: 'User research',
        icon: <IconMicrophone />,
        accentColor: 'var(--color-product-user-interviews-light)',
        accentColorDark: 'var(--color-product-user-interviews-dark)',
        hedgehog: HedgehogReporter,
        text: {
            'needs-setup': {
                headline: 'Run user interviews without booking a single call',
                lead: 'Create a research topic with the questions you want answered and the users to ask. An AI voice agent runs each interview, and transcripts and summaries land here as responses come in. You can then search across every response for what users said about any subject.',
            },
        },
        PrimaryAction: NewTopicButton,
        skippable: false,
        previewLabel: 'Your research, once responses arrive',
        Preview: UserInterviewPreview,
    },
}
