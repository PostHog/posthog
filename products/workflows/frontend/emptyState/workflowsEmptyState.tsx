import * as workflowsPng from '@posthog/brand/hoggies/png/workflows'
import { IconDecisionTree } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { WorkflowsPreview } from './WorkflowsPreview'
import { workflowsSetupLogic } from './workflowsSetupLogic'

const HedgehogWorkflows = pngHoggie(workflowsPng)

export const workflowsEmptyState: SceneProductEmptyState = {
    statusLogic: workflowsSetupLogic,
    // One scene serves every tab here, but only the workflow list is the product being gated.
    // Channels, the message library, opt-outs, suppression, and reputation configure resources
    // that stand on their own, and a person often sets a channel up before a first workflow.
    scenes: [{ scene: Scene.Workflows, tabs: [undefined, 'workflows'] }],
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
