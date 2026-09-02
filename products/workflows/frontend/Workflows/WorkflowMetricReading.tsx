import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import type { WorkflowProposalMetricApi } from '../generated/api.schemas'
import { MIN_EVIDENCE_SAMPLE, formatValue } from './suggestionEvidence'

export function WorkflowMetricReading({ reading }: { reading: WorkflowProposalMetricApi }): JSX.Element {
    return (
        <span className="flex items-center gap-1 flex-wrap">
            {reading.metric} {formatValue(reading.value) ?? 'no data'}
            <span className="text-secondary">(n={reading.n})</span>
            {reading.below_minimum_sample && (
                <Tooltip title={`Under ${MIN_EVIDENCE_SAMPLE} observations. Not enough to call this a result.`}>
                    <LemonTag type="warning">Too little data</LemonTag>
                </Tooltip>
            )}
        </span>
    )
}
