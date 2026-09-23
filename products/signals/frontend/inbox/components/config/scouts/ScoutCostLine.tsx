import { Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { ScoutCostRollup, scoutCostLineParts, scoutCostWindowLabel } from '../../../utils/scoutCosts'
import { formatRunCost } from '../../../utils/scoutRunsWindow'

/**
 * What a scout costs, on one line: per day, per run, and per report. Staff only, and rendered only
 * where a rollup exists, so a scout with no priced run in the window shows nothing rather than zero.
 */
export function ScoutCostLine({ rollup }: { rollup: ScoutCostRollup }): JSX.Element {
    const tooltip = [
        `${formatRunCost(rollup.spendUsd)} in the ${scoutCostWindowLabel(rollup.windowDays)}`,
        `${pluralize(rollup.pricedRunCount, 'priced run')}`,
        rollup.reportsTouched > 0
            ? `${pluralize(rollup.reportsTouched, 'report')} filed or added to`
            : 'no reports filed or added to',
    ].join(' · ')

    return (
        <Tooltip title={tooltip}>
            <span className="tabular-nums">{scoutCostLineParts(rollup).join(' · ')}</span>
        </Tooltip>
    )
}
