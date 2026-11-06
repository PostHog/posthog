import { useValues } from 'kea'

import { IconRocket } from '@posthog/icons'
import type { LemonTagType } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { defineNotebookWidgetViews } from 'scenes/notebooks/notebookWidgetCatalog'
import { NotebookNodeProps } from 'scenes/notebooks/types'

import { EarlyAccessFeatureStage } from '~/types'

import { EarlyAccessFeatureLogicProps, earlyAccessFeatureLogic } from './earlyAccessFeatureLogic'

export type EarlyAccessFeatureNotebookWidgetAttributes = {
    id: EarlyAccessFeatureLogicProps['id']
    view?: string
}

export function getEarlyAccessFeatureStageTagType(stage: EarlyAccessFeatureStage): LemonTagType {
    if (stage === EarlyAccessFeatureStage.Beta) {
        return 'warning'
    }
    if (stage === EarlyAccessFeatureStage.GeneralAvailability) {
        return 'success'
    }
    return 'default'
}

export function getEarlyAccessFeatureStageLabel(stage: EarlyAccessFeatureStage): string {
    return stage === EarlyAccessFeatureStage.GeneralAvailability ? 'General availability' : stage
}

function EarlyAccessFeatureSummary({
    attributes,
}: NotebookNodeProps<EarlyAccessFeatureNotebookWidgetAttributes>): JSX.Element {
    const { id } = attributes
    const { earlyAccessFeature, earlyAccessFeatureLoading, earlyAccessFeatureMissing } = useValues(
        earlyAccessFeatureLogic({ id })
    )

    if (earlyAccessFeatureMissing) {
        return <NotFound object="early access feature" />
    }

    if (earlyAccessFeatureLoading) {
        return (
            <div className="flex items-center gap-2 p-3">
                <IconRocket className="text-lg" />
                <LemonSkeleton className="h-6 flex-1" />
            </div>
        )
    }

    return <div className="p-3 text-xs text-secondary">{earlyAccessFeature.description || 'No description'}</div>
}

export const EARLY_ACCESS_FEATURE_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<
    EarlyAccessFeatureNotebookWidgetAttributes,
    'EarlyAccessFeature'
>('EarlyAccessFeature', {
    summary: EarlyAccessFeatureSummary,
})
