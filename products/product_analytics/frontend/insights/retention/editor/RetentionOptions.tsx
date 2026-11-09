import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'
import { Button, cn } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { FEATURE_FLAGS } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils/strings'
import { insightLogic } from 'scenes/insights/insightLogic'

import { RetentionAggregationSelector } from '../filters/RetentionAggregationSelector'
import { RetentionCumulativeButton } from '../filters/RetentionCumulativeButton'
import { RetentionMeanDropdown } from '../filters/RetentionMeanDropdown'
import { RetentionMinimumOccurrencesInput } from '../filters/RetentionMinimumOccurrencesInput'
import { RetentionReferencePicker } from '../filters/RetentionReferencePicker'
import { RetentionTimeWindowModePicker } from '../filters/RetentionTimeWindowModePicker'
import { retentionLogic } from '../retentionLogic'

const RETENTION_DOCS_URL =
    'https://posthog.com/docs/product-analytics/retention?utm_campaign=learn-more-horizontal&utm_medium=in-product'

export function RetentionOptions(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(retentionLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const quillSurface = useQuillSurface()
    const { minimumOccurrences = 1, aggregationType } = retentionFilter || {}
    const rowClassName = cn('flex items-center gap-2', quillSurface && 'flex-wrap')

    return (
        <div className="deprecated-space-y-3" data-attr="retention-options">
            {featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_RETENTION_AGGREGATION] && (
                <div className={cn('flex items-start gap-2', quillSurface && 'flex-wrap')}>
                    <div className="mt-1.5">Calculate</div>
                    <RetentionAggregationSelector />
                </div>
            )}
            {(!aggregationType || aggregationType === 'count') && (
                <>
                    <div className={rowClassName}>
                        <div>Retention relative to</div>
                        <RetentionReferencePicker />
                    </div>
                    <div className={rowClassName}>
                        <div>When users return</div>
                        <RetentionCumulativeButton />
                        <div>the interval</div>
                    </div>
                    <div className={rowClassName}>
                        <div>When users return at least</div>
                        <RetentionMinimumOccurrencesInput />
                        <div>{pluralize(minimumOccurrences, 'time', 'times', false)} in an interval</div>
                    </div>
                    <div className={rowClassName}>
                        <div>Mean calculation logic</div>
                        <RetentionMeanDropdown />
                    </div>
                    <div className={rowClassName}>
                        <div>Time window</div>
                        <RetentionTimeWindowModePicker />
                    </div>
                </>
            )}

            {quillSurface ? (
                <div>
                    <Button
                        variant="link"
                        size="inline"
                        render={<LinkPrimitive to={RETENTION_DOCS_URL} target="_blank" />}
                    >
                        Learn more in docs
                    </Button>
                </div>
            ) : (
                <div>
                    <p className="text-secondary mt-4">
                        <Link to={RETENTION_DOCS_URL} target="_blank" className="inline-flex items-center">
                            Learn more in docs
                        </Link>
                    </p>
                </div>
            )}
        </div>
    )
}
