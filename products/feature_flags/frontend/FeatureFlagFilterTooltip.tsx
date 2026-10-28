import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { featureFlagFilterSummaryLogic } from './featureFlagFilterSummaryLogic'

export function FeatureFlagFilterTooltip({ flagKey }: { flagKey: string }): JSX.Element | null {
    const { summary, flagLoading } = useValues(featureFlagFilterSummaryLogic({ flagKey }))

    if (flagLoading) {
        return <Spinner />
    }
    if (!summary) {
        return null
    }

    return (
        <div className="mt-1" data-attr="feature-flag-filter-tooltip">
            <div>{summary.active ? 'Enabled' : 'Disabled'}</div>
            {summary.conditionCount !== null && (
                <div>{pluralize(summary.conditionCount, 'release condition', 'release conditions')}</div>
            )}
            {summary.variants &&
                (summary.variants.length > 0 ? (
                    <div>
                        Variants:{' '}
                        {summary.variants
                            .map((variant) => `${variant.key} (${variant.rollout_percentage}%)`)
                            .join(', ')}
                    </div>
                ) : (
                    <div>No variants (true or false)</div>
                ))}
        </div>
    )
}
