import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { InsightLogicProps } from '~/types'

import { InsightDataCheckRow } from './InsightDataCheckRow'
import { insightDataChecksLogic } from './insightDataChecksLogic'

export function InsightDataChecksList({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    const { status, checks, result, checkedQuery } = useValues(insightDataChecksLogic(insightProps))
    const { loadDataChecks } = useActions(insightDataChecksLogic(insightProps))

    return (
        <div className="flex flex-col gap-3 p-2 w-100 max-w-full" data-attr="insight-data-checks-list">
            <h5 className="m-0">Checks we've run on this data</h5>
            {status === 'checking' ? (
                <div className="flex flex-col gap-2" aria-busy="true">
                    <LemonSkeleton className="h-4 w-3/4" />
                    <LemonSkeleton className="h-4 w-2/3" />
                    <LemonSkeleton className="h-4 w-3/4" />
                    <LemonSkeleton className="h-4 w-1/2" />
                </div>
            ) : status === 'failed' ? (
                <div className="flex flex-col gap-2 items-start">
                    <span>The checks didn't finish. The chart's own numbers are not affected.</span>
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={() => checkedQuery && loadDataChecks(checkedQuery)}
                        data-attr="insight-data-checks-retry"
                    >
                        Run the checks again
                    </LemonButton>
                </div>
            ) : (
                <>
                    <ul className="flex flex-col gap-3 m-0 p-0 list-none">
                        {checks.map((check) => (
                            <InsightDataCheckRow key={check.key} insightProps={insightProps} check={check} />
                        ))}
                    </ul>
                    {result && (
                        <span className="text-xs text-secondary">
                            {!result.events_checked
                                ? 'No events match this chart, so there is nothing to check.'
                                : result.sample_rate < 1
                                  ? `Checked a sample of ${humanFriendlyNumber(result.events_checked)} of this chart's events.`
                                  : `${humanFriendlyNumber(result.events_checked)} events checked.`}
                        </span>
                    )}
                </>
            )}
        </div>
    )
}
