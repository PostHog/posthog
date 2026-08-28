import * as workflowsPng from '@posthog/brand/hoggies/png/workflows'
import { IconDecisionTree } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { WorkflowsPreview } from './WorkflowsPreview'
import { workflowsSetupLogic } from './workflowsSetupLogic'

const HedgehogWorkflows = pngHoggie(workflowsPng)

export const workflowsEmptyState: SceneProductEmptyState = {
    statusLogic: workflowsSetupLogic,
    config: {
        productKey: ProductKey.WORKFLOWS,
        productName: 'Workflows',
        icon: <IconDecisionTree />,
        accentColor: 'var(--color-product-workflows-light)',
        accentColorDark: 'var(--color-product-workflows-dark)',
        hedgehog: HedgehogWorkflows,
        text: {
            'needs-setup': {
                headline: 'Message users when it matters',
                lead: 'Build journeys on a canvas: trigger on any event or cohort, wait, branch on behavior, and send email, SMS, or push. Connect a channel and design your first message along the way.',
            },
        },
        primaryAction: {
            label: 'New workflow',
            to: urls.workflowNew(),
        },
        docsUrl: 'https://posthog.com/docs/workflows',
        previewLabel: 'Your journeys, once running',
        Preview: WorkflowsPreview,
    },
}
