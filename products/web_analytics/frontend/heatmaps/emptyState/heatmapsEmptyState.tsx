import * as cursorPng from '@posthog/brand/hoggies/png/cursor'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { IconHeatmap } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { HeatmapsPreview } from './HeatmapsPreview'
import { heatmapsSetupLogic } from './heatmapsSetupLogic'

const HedgehogCursor = pngHoggie(cursorPng)

export const heatmapsEmptyState: SceneProductEmptyState = {
    statusLogic: heatmapsSetupLogic,
    config: {
        productKey: ProductKey.HEATMAPS,
        productName: 'Heatmaps',
        icon: <IconHeatmap />,
        accentColor: 'var(--color-product-heatmaps-light)',
        accentColorDark: 'var(--color-product-heatmaps-dark)',
        hedgehog: HedgehogCursor,
        text: {
            'needs-setup': {
                headline: 'See where people click, scroll, and give up',
                lead: 'A heatmap lays clicks, rage clicks, dead clicks, mouse movement, and scroll depth over a screenshot of one of your pages. Save a heatmap for a page you care about, pick the viewport widths to compare, and open it whenever you want to know how far people get and which elements they actually use.',
            },
        },
        primaryAction: {
            label: 'Create your first heatmap',
            to: urls.heatmap('new'),
            accessControl: {
                resourceType: AccessControlResourceType.Heatmap,
                minAccessLevel: AccessControlLevel.Editor,
            },
            dataAttr: 'heatmaps-new-heatmap-button',
        },
        skippable: false,
        docsUrl: 'https://posthog.com/docs/toolbar/heatmaps',
        previewLabel: 'Your heatmap, once saved',
        Preview: HeatmapsPreview,
    },
}
