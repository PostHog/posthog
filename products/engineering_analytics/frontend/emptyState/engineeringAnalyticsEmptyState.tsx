import * as codingGroupPng from '@posthog/brand/hoggies/png/coding-group'
import { IconGitBranch } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { EngineeringAnalyticsPreview } from './EngineeringAnalyticsPreview'
import { engineeringAnalyticsSetupLogic } from './engineeringAnalyticsSetupLogic'

const HedgehogCodingGroup = pngHoggie(codingGroupPng)

export const engineeringAnalyticsEmptyState: SceneProductEmptyState = {
    statusLogic: engineeringAnalyticsSetupLogic,
    config: {
        productKey: ProductKey.ENGINEERING_ANALYTICS,
        productName: 'Engineering analytics',
        icon: <IconGitBranch />,
        // The nav item borrows the data warehouse color too: this product is a view over a warehouse source.
        accentColor: 'var(--color-product-data-warehouse-light)',
        accentColorDark: 'var(--color-product-data-warehouse-dark)',
        hedgehog: HedgehogCodingGroup,
        text: {
            'needs-setup': {
                headline: 'See how fast pull requests ship and where CI slows them down',
                lead: 'Engineering analytics reads pull requests and workflow runs from a GitHub source in your data warehouse. It shows time from open to merge, CI pass rates and durations per workflow, flaky tests, and how each team compares, without any changes to your repositories.',
                hint: 'Connect the GitHub source and the first sync fills the charts:',
            },
        },
        primaryAction: {
            label: 'Connect a GitHub source',
            to: urls.dataWarehouseSourceNew('Github'),
            dataAttr: 'engineering-analytics-connect-github',
        },
        skippable: false,
        previewLabel: 'Your pull requests, once synced',
        Preview: EngineeringAnalyticsPreview,
    },
}
