import type { RunActionHistoryDTOApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { failureMessage } from './subscriptionPulseDeliveryUtils'

const GATE_STATUS: Record<string, string> = {
    pending: 'Build and tests pending',
    passed: 'Build and tests passed',
    failed: 'Build or tests failed',
    unavailable: 'Build and test policy unavailable',
}

const GATE_ITEM_STATUS: Record<string, string> = {
    pending: 'Pending',
    passed: 'Passed',
    failed: 'Failed',
    unavailable: 'Unavailable',
}

export function SubscriptionPulseBuildTestGate({ action }: { action: RunActionHistoryDTOApi }): JSX.Element | null {
    const gate = action.build_test_gate
    if (!gate) {
        return null
    }
    const failure = failureMessage(gate.failure_code)
    return (
        <div className="flex flex-col gap-1">
            <span className={gate.status === 'failed' || gate.status === 'unavailable' ? 'text-danger' : undefined}>
                <span className="font-medium text-primary">{action.title}</span>:{' '}
                {GATE_STATUS[gate.status] ?? 'Build and test status unavailable'}.
            </span>
            {gate.gates.length > 0 ? (
                <span>
                    {gate.gates
                        .map((item) => `${item.label}: ${GATE_ITEM_STATUS[item.status] ?? 'Unknown'}`)
                        .join(' · ')}
                </span>
            ) : null}
            {failure ? <span className="text-danger">{failure}</span> : null}
        </div>
    )
}
