import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonSegmentedButton } from '@posthog/lemon-ui'

import { MONITORING_CONNECTIONS, type MonitoringConnection, monitoringTabLogic } from '../../logics/monitoringTabLogic'

const CONNECTION_LABEL: Record<MonitoringConnection, string> = {
    assigned: "You're assigned, or your agent is",
    suggested_reviewer: "You're a suggested reviewer",
}

export function MonitoringScopeControl(): JSX.Element {
    const { scope } = useValues(monitoringTabLogic)
    const { setScope } = useActions(monitoringTabLogic)
    const count = scope.connections.length

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonSegmentedButton
                size="small"
                value={scope.everyone ? 'everyone' : 'mine'}
                onChange={(value) => setScope({ ...scope, everyone: value === 'everyone' })}
                options={[
                    { value: 'mine', label: 'For you', 'data-attr': 'inbox-monitoring-scope-mine' },
                    { value: 'everyone', label: 'Everyone', 'data-attr': 'inbox-monitoring-scope-everyone' },
                ]}
            />
            <LemonDropdown
                closeOnClickInside={false}
                placement="bottom-end"
                overlay={
                    <div className="flex flex-col gap-2 p-2">
                        <div className="text-xs font-semibold text-secondary">Show reports where</div>
                        {MONITORING_CONNECTIONS.map((connection) => (
                            <LemonCheckbox
                                key={connection}
                                label={CONNECTION_LABEL[connection]}
                                checked={scope.connections.includes(connection)}
                                data-attr={`inbox-monitoring-connection-${connection}`}
                                onChange={(checked) =>
                                    setScope({
                                        ...scope,
                                        connections: checked
                                            ? [...scope.connections, connection]
                                            : scope.connections.filter((c) => c !== connection),
                                    })
                                }
                            />
                        ))}
                    </div>
                }
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconFilter />}
                    disabledReason={scope.everyone ? 'Everyone shows every report' : undefined}
                    data-attr="inbox-monitoring-connections"
                >
                    {count === MONITORING_CONNECTIONS.length
                        ? 'All connections'
                        : `${count} of ${MONITORING_CONNECTIONS.length} connections`}
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}
