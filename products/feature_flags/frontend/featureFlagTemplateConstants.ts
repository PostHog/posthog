import { IconRocket, IconServer } from '@posthog/icons'

import type { FlagIntent } from 'scenes/feature-flags/featureFlagIntentWarningLogic'

export type TemplateKey = 'simple' | 'targeted' | 'multivariate' | 'targeted-multivariate'

export const TEMPLATE_NAMES: Record<TemplateKey, string> = {
    simple: 'Percentage rollout',
    targeted: 'Targeted release',
    multivariate: 'Multivariate',
    'targeted-multivariate': 'Targeted Multivariate',
}

export interface IntentMetadata {
    name: string
    description: string
    icon: React.ComponentType<{ className?: string }>
}

export const INTENT_METADATA: Record<FlagIntent, IntentMetadata> = {
    'local-eval': {
        name: 'Local evaluation',
        description: 'Evaluate flags server-side without network requests',
        icon: IconServer,
    },
    'first-page-load': {
        name: 'Prevent flicker',
        description: 'Avoid flags evaluating to false on first load',
        icon: IconRocket,
    },
}

export const INTENT_KEYS: FlagIntent[] = ['local-eval', 'first-page-load']
