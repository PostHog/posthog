import { LemonTag } from '@posthog/lemon-ui'

import { MCPDiscoverCandidateApiMeasured } from './generated/api.schemas'

function numberFrom(measured: MCPDiscoverCandidateApiMeasured, key: string): number | null {
    const value = measured?.[key]
    return typeof value === 'number' ? value : null
}

export function MeasuredTag({ measured }: { measured: MCPDiscoverCandidateApiMeasured }): JSX.Element | null {
    const calls = numberFrom(measured, 'calls')
    if (calls === null) {
        return null
    }
    const errorRate = numberFrom(measured, 'error_rate_pct')
    const success = errorRate === null ? null : `${(100 - errorRate).toFixed(1)}% success`
    return (
        <LemonTag type="highlight">
            {calls.toLocaleString()} real calls{success ? `, ${success}` : ''}
        </LemonTag>
    )
}
