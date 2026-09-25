import { BindLogic } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LogsFeatureFlagKeys } from 'products/logs/frontend/logsFeatureFlagKeys'

import { logsSourcesLogic } from './logsSourcesLogic'
import { LogsSourcesTable } from './LogsSourcesTable'
import { LogsSourceWizard } from './LogsSourceWizard'

export function LogsSourcesSection(): JSX.Element | null {
    const enabled = useFeatureFlag(LogsFeatureFlagKeys.cloudSources)
    if (!enabled) {
        return null
    }
    return (
        <BindLogic logic={logsSourcesLogic} props={{}}>
            <div className="space-y-3">
                <p className="text-muted m-0">
                    PostHog gives you an endpoint for an Amazon Data Firehose stream, and subscription filters on your
                    log groups deliver into it. Your AWS account is billed for Firehose usage.
                </p>
                <LogsSourcesTable />
                <LogsSourceWizard />
            </div>
        </BindLogic>
    )
}
