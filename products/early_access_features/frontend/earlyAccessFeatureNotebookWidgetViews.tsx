import { useValues } from 'kea'

import { IconRocket } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

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

    return (
        <div className="flex flex-wrap items-center gap-2 p-3">
            <IconRocket className="text-lg shrink-0" />
            <div className="flex min-w-48 flex-1 flex-col">
                <span className="truncate font-semibold">{earlyAccessFeature.name}</span>
                {earlyAccessFeature.description ? (
                    <span className="truncate text-xs text-secondary">{earlyAccessFeature.description}</span>
                ) : null}
            </div>
            <LemonTag
                type={
                    earlyAccessFeature.stage === EarlyAccessFeatureStage.Beta
                        ? 'warning'
                        : earlyAccessFeature.stage === EarlyAccessFeatureStage.GeneralAvailability
                          ? 'success'
                          : 'default'
                }
                className="uppercase"
            >
                {earlyAccessFeature.stage}
            </LemonTag>
        </div>
    )
}

export const EARLY_ACCESS_FEATURE_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<
    EarlyAccessFeatureNotebookWidgetAttributes,
    'EarlyAccessFeature'
>('EarlyAccessFeature', {
    summary: EarlyAccessFeatureSummary,
})
