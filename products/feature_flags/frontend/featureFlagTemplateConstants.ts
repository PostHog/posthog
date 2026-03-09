import { type ComponentType } from 'react'

import { IconRocket, IconServer } from '@posthog/icons'

import type { FlagIntent } from 'scenes/feature-flags/featureFlagIntentWarningLogic'

export type TemplateKey = 'simple' | 'targeted' | 'multivariate' | 'targeted-multivariate'

export const TEMPLATE_NAMES: Record<TemplateKey, string> = {
    simple: 'Percentage rollout',
    targeted: 'Targeted release',
    multivariate: 'Multivariate',
    'targeted-multivariate': 'Targeted multivariate',
}

export interface IntentMetadata {
    name: string
    description: string
    icon: ComponentType<{ className?: string }>
    consequence: string
    docUrl: string
}

export const INTENT_METADATA: Record<FlagIntent, IntentMetadata> = {
    'local-eval': {
        name: 'Local evaluation',
        description: 'Evaluate flags server-side without network requests',
        icon: IconServer,
        consequence:
            'These will force a server request to evaluate this flag, removing the speed and cost benefits of local evaluation.',
        docUrl: 'https://posthog.com/docs/feature-flags/local-evaluation#restriction-on-local-evaluation',
    },
    'first-page-load': {
        name: 'Prevent flicker',
        description: 'Avoid flags evaluating to false on first load',
        icon: IconRocket,
        consequence:
            'These may cause the flag to briefly return the wrong value on first page load, resulting in a visible flicker.',
        docUrl: 'https://posthog.com/docs/feature-flags/bootstrapping',
    },
}

export const INTENT_KEYS: FlagIntent[] = ['local-eval', 'first-page-load']
