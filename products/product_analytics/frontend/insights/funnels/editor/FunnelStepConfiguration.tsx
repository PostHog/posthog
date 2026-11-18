import { useValues } from 'kea'

import { Field, FieldTitle } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'

import { groupsModel } from '~/models/groupsModel'
import { EditorFilterProps } from '~/types'

import { FunnelConversionWindowFilter } from 'products/product_analytics/frontend/insights/funnels/filters/FunnelConversionWindowFilter'
import { AggregationSelect } from 'products/product_analytics/frontend/insights/shared/AggregationSelect'

export function FunnelStepConfiguration({ insightProps }: EditorFilterProps): JSX.Element {
    const { showGroupsOptions } = useValues(groupsModel)
    const quillSurface = useQuillSurface()

    return (
        <div className="flex flex-col gap-4">
            {showGroupsOptions &&
                (quillSurface ? (
                    <Field
                        orientation="horizontal"
                        className="flex-wrap justify-between"
                        data-attr="funnel-aggregation-filter"
                    >
                        <FieldTitle className="font-normal">Aggregating by</FieldTitle>
                        <AggregationSelect insightProps={insightProps} hogqlAvailable />
                    </Field>
                ) : (
                    <div className="flex items-center w-full gap-2" data-attr="funnel-aggregation-filter">
                        <span>Aggregating by</span>
                        <AggregationSelect insightProps={insightProps} hogqlAvailable />
                    </div>
                ))}
            <FunnelConversionWindowFilter insightProps={insightProps} />
        </div>
    )
}
