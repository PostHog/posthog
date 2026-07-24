import { BindLogic } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LogsFeatureFlagKeys } from 'products/logs/frontend/logsFeatureFlagKeys'

import { LogsSamplingRulesSortableTable } from './LogsSamplingRulesSortableTable'
import { logsSamplingSectionLogic } from './logsSamplingSectionLogic'

export function LogsSamplingSection(): JSX.Element | null {
    const enabled = useFeatureFlag(LogsFeatureFlagKeys.dropRules)
    if (!enabled) {
        return null
    }
    return (
        <BindLogic logic={logsSamplingSectionLogic} props={{}}>
            <div className="space-y-3">
                <p className="text-muted m-0">
                    Exclude noisy or sensitive lines before they are stored. Rules run top to bottom during ingestion —
                    drag the handle on each row to change that order. Use Drop to remove matching lines, or Rate limit
                    to cap a service's volume.
                </p>
                <LogsSamplingRulesSortableTable />
            </div>
        </BindLogic>
    )
}
