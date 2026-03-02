import type { FlagIntent } from 'scenes/feature-flags/featureFlagIntentWarningLogic'

export type TemplateKey = 'simple' | 'targeted' | 'multivariate' | 'targeted-multivariate'

export const TEMPLATE_NAMES: Record<TemplateKey, string> = {
    simple: 'Percentage rollout',
    targeted: 'Targeted release',
    multivariate: 'Multivariate',
    'targeted-multivariate': 'Targeted Multivariate',
}

export const INTENT_NAMES: Record<FlagIntent, string> = {
    'local-eval': 'Local evaluation',
    'first-page-load': 'Prevent flicker',
}
