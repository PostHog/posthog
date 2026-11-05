import { useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTag, type LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { formatTimestamp } from '../../setupInspector/setupInspectorUtils'
import { experimentHealthDebugLogic } from './experimentHealthDebugLogic'
import { HEALTH_DEBUG_DOMAIN_LABELS, type HealthDebugCheck } from './healthDebugReport'

const SEVERITY_TAG_TYPES: Record<NonNullable<HealthDebugCheck['severity']>, LemonTagType> = {
    critical: 'danger',
    warning: 'warning',
    info: 'muted',
}

function ComputedAt({ timestamp }: { timestamp: string }): JSX.Element {
    return (
        <span className="text-xs text-secondary" translate="no">
            computed {formatTimestamp(timestamp)}
        </span>
    )
}

export function HealthDebugCheckResults(): JSX.Element {
    const { experimentId } = useValues(experimentLogic)
    const { healthDebugChecks } = useValues(experimentHealthDebugLogic({ experimentId }))
    const { setActiveDomain } = useActions(experimentHealthDebugLogic({ experimentId }))

    return (
        <LemonTable<HealthDebugCheck>
            size="small"
            dataSource={healthDebugChecks}
            rowKey="check"
            columns={[
                {
                    title: 'Check',
                    key: 'check',
                    render: (_, check) => (
                        <div className="flex flex-col">
                            <code translate="no">{check.check}</code>
                            <span className="text-secondary text-xs">from the {check.source}</span>
                        </div>
                    ),
                },
                {
                    title: 'Result',
                    key: 'result',
                    render: (_, check) => (
                        <div className="flex flex-col gap-1">
                            <span className="flex flex-wrap items-center gap-1">
                                {check.severity && (
                                    <LemonTag type={SEVERITY_TAG_TYPES[check.severity]}>{check.severity}</LemonTag>
                                )}
                                <code translate="no">{check.result}</code>
                                {check.computedAt && <ComputedAt timestamp={check.computedAt} />}
                            </span>
                            {check.browser !== null && (
                                <span className="flex flex-wrap items-center gap-1 text-xs text-secondary">
                                    <span>{check.browserLabel}:</span>
                                    <code translate="no">{check.browser}</code>
                                    {check.browserComputedAt && <ComputedAt timestamp={check.browserComputedAt} />}
                                    {check.difference === 'disagrees' && <LemonTag type="danger">Differs</LemonTag>}
                                    {check.difference === 'drift' && (
                                        <Tooltip title="The page's exposure answer is cached apart from the server's and computed at another time, so the two can differ. The panel shows the page's.">
                                            <LemonTag type="muted">Drift</LemonTag>
                                        </Tooltip>
                                    )}
                                </span>
                            )}
                        </div>
                    ),
                },
                {
                    title: 'Reads',
                    key: 'reads',
                    render: (_, check) => (
                        <div className="flex flex-wrap gap-1 min-w-44">
                            {check.reads.map((domain) => (
                                <LemonButton
                                    key={domain}
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() => setActiveDomain(domain)}
                                    data-attr="experiment-health-debug-reads"
                                >
                                    {HEALTH_DEBUG_DOMAIN_LABELS[domain]}
                                </LemonButton>
                            ))}
                        </div>
                    ),
                },
                {
                    title: 'Details',
                    key: 'note',
                    render: (_, check) => <span className="text-xs">{check.note}</span>,
                },
            ]}
        />
    )
}
