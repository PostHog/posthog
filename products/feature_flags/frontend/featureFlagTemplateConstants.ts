export type TemplateKey = 'simple' | 'targeted' | 'multivariate' | 'targeted-multivariate'

export const TEMPLATE_NAMES: Record<TemplateKey, string> = {
    simple: 'Percentage rollout',
    targeted: 'Targeted release',
    multivariate: 'Multivariate',
    'targeted-multivariate': 'Targeted Multivariate',
}
