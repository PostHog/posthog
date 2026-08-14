import { BindLogic } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LogsFeatureFlagKeys } from 'products/logs/frontend/logsFeatureFlagKeys'

import { LogsRetentionRulesSortableTable } from './LogsRetentionRulesSortableTable'
import { logsRetentionSectionLogic } from './logsRetentionSectionLogic'

export function LogsRetentionSection(): JSX.Element | null {
    const enabled = useFeatureFlag(LogsFeatureFlagKeys.retentionRules)
    if (!enabled) {
        return null
    }
    return (
        <BindLogic logic={logsRetentionSectionLogic} props={{}}>
            <div className="space-y-3">
                <p className="text-muted m-0">
                    Keep some logs longer or shorter than the environment default. Rules run top to bottom during
                    ingestion — drag the handle on each row to change that order, and the first matching rule sets a
                    log's retention. Logs matching no rule keep the environment default. Retention is applied at ingest,
                    so changes only affect logs received from that point onwards.
                </p>
                <LogsRetentionRulesSortableTable />
            </div>
        </BindLogic>
    )
}
