import { BindLogic } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { userHasAccess } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { LogsFeatureFlagKeys } from 'products/logs/frontend/logsFeatureFlagKeys'

import { LogsSamplingRulesSortableTable } from './LogsSamplingRulesSortableTable'
import { logsSamplingSectionLogic } from './logsSamplingSectionLogic'

export function LogsSamplingSection(): JSX.Element | null {
    const enabled = useFeatureFlag(LogsFeatureFlagKeys.dropRules)
    if (!enabled) {
        return null
    }
    // The drop-rules endpoints are RBAC-gated on the logs resource independently of the feature
    // flag. Without at least viewer access the list request 403s, so hide the panel rather than
    // mount the logic and fire a request we know will fail.
    if (!userHasAccess(AccessControlResourceType.Logs, AccessControlLevel.Viewer)) {
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
