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
                    Exclude noisy or sensitive lines before they are stored. Drop rules apply first in top-to-bottom
                    order; rate limit rules apply last, only to records no drop rule resolved. Drag the handle on each
                    row to reorder.
                </p>
                <LogsSamplingRulesSortableTable />
            </div>
        </BindLogic>
    )
}
