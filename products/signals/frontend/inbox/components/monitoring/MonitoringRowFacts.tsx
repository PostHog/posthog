import { useValues } from 'kea'

import { userLogic } from 'scenes/userLogic'

import type { SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

import { monitoringWindowProgress } from '../../utils/reportMonitoringSummary'
import { MonitoringTime } from './MonitoringTime'

function Fact({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex justify-between gap-3 text-xs">
            <span className="text-tertiary">{label}</span>
            <span className="text-right">{children}</span>
        </div>
    )
}

export function MonitoringRowFacts({ report, now }: { report: SignalReportListApi; now: number }): JSX.Element {
    const { user } = useValues(userLogic)
    const ongoing = !report.monitoring_outcome ? report.monitoring_summary : null
    const assignee = report.assignee?.responsible_user ?? null
    const assignedToYou = !!user && assignee?.uuid === user.uuid
    const yourConnections = [
        assignedToYou ? 'Assigned to you' : null,
        report.is_suggested_reviewer ? 'Suggested reviewer' : null,
    ].filter(Boolean)
    const progress = ongoing ? monitoringWindowProgress(ongoing, now) : null

    return (
        <div className="flex flex-col gap-1">
            {report.monitoring_started_at ? (
                <Fact label="Started">
                    <MonitoringTime iso={report.monitoring_started_at} />
                </Fact>
            ) : null}
            {ongoing ? (
                <Fact label="Verdict">
                    <MonitoringTime iso={ongoing.ends_at} />
                </Fact>
            ) : null}
            {progress ? <Fact label="Window">{progress}</Fact> : null}
            {yourConnections.length ? <Fact label="You">{yourConnections.join(' · ')}</Fact> : null}
            {assignee && !assignedToYou ? (
                <Fact label="Assigned to">{assignee.first_name || assignee.email}</Fact>
            ) : null}
        </div>
    )
}
