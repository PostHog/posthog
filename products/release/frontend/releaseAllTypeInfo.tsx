import { IconFlag, IconFlask, IconRocket, IconToggle } from '@posthog/icons'

import type { ReleaseAllType } from './releaseAllLogic'

export interface ReleaseAllTypeInfo {
    label: string
    pluralLabel: string
    icon: JSX.Element
    color: string
}

export const RELEASE_ALL_TYPE_INFO: Record<ReleaseAllType, ReleaseAllTypeInfo> = {
    release: { label: 'Release', pluralLabel: 'Releases', icon: <IconFlag />, color: 'var(--muted-foreground)' },
    feature_flag: {
        label: 'Feature flag',
        pluralLabel: 'Feature flags',
        icon: <IconToggle />,
        color: 'var(--color-product-feature-flags-light)',
    },
    experiment: {
        label: 'Experiment',
        pluralLabel: 'Experiments',
        icon: <IconFlask />,
        color: 'var(--color-product-experiments-light)',
    },
    early_access_feature: {
        label: 'Early access feature',
        pluralLabel: 'Early access features',
        icon: <IconRocket />,
        color: 'var(--color-product-early-access-features-light)',
    },
}
