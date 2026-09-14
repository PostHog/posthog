import * as readingPng from '@posthog/brand/hoggies/png/reading'
import { IconNotebook } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { NotebooksPreview } from './NotebooksPreview'
import { notebooksSetupLogic } from './notebooksSetupLogic'

const HedgehogReading = pngHoggie(readingPng)

export const notebooksEmptyState: SceneProductEmptyState = {
    statusLogic: notebooksSetupLogic,
    config: {
        productKey: ProductKey.NOTEBOOKS,
        productName: 'Notebooks',
        icon: <IconNotebook />,
        accentColor: 'var(--color-product-notebooks-light)',
        accentColorDark: 'var(--color-product-notebooks-dark)',
        hedgehog: HedgehogReading,
        text: {
            'needs-setup': {
                headline: 'Write up what you found, next to the data you found it in',
                lead: 'A notebook holds your writing and live PostHog data in one page: insights, session replays, feature flags, and events. Every block re-runs its query when someone opens the notebook, so the analysis you share stays current instead of freezing into a screenshot.',
            },
        },
        primaryAction: {
            label: 'Create your first notebook',
            to: urls.notebook('new'),
            dataAttr: 'new-notebook',
            accessControl: {
                resourceType: AccessControlResourceType.Notebook,
                minAccessLevel: AccessControlLevel.Editor,
            },
        },
        docsUrl: 'https://posthog.com/docs/notebooks',
        previewLabel: 'A notebook, once written',
        Preview: NotebooksPreview,
    },
}
