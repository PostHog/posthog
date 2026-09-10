import * as doctorPng from '@posthog/brand/hoggies/png/doctor-1'
import { IconPulse } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import { PulsePreview } from './PulsePreview'
import { PulsePrimaryAction } from './PulsePrimaryAction'
import { pulseSetupLogic } from './pulseSetupLogic'

const HedgehogDoctor = pngHoggie(doctorPng)

export const pulseEmptyState: SceneProductEmptyState = {
    statusLogic: pulseSetupLogic,
    // The whole product is behind this flag; the scene's own 404 gate handles the flag-off case.
    featureFlag: FEATURE_FLAGS.PULSE,
    config: {
        productKey: ProductKey.PULSE,
        productName: 'Pulse',
        icon: <IconPulse />,
        accentColor: 'var(--color-product-activity-light)',
        accentColorDark: 'var(--color-product-activity-dark)',
        hedgehog: HedgehogDoctor,
        text: {
            'needs-setup': {
                headline: 'Get a brief on what changed and what to do about it',
                lead: 'Pulse reads your product data, writes a brief on what moved and why, and turns the findings into opportunities with a suggested next step and the numbers behind it. Run a brief for the whole project, or set a focus such as onboarding completion to get briefs about one goal.',
                hint: 'Your first brief takes a few minutes to generate:',
            },
        },
        PrimaryAction: PulsePrimaryAction,
        skippable: false,
        previewLabel: 'Your brief, once generated',
        Preview: PulsePreview,
    },
}
