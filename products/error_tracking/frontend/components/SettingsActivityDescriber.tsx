import {
    ActivityChange,
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'

const RATE_LIMIT_LABELS: Record<string, string> = {
    project_rate_limit_value: 'project exception rate limit',
    per_issue_rate_limit_value: 'per-issue exception rate limit',
}

const BUCKET_LABELS: Record<string, string> = {
    project_rate_limit_bucket_size_minutes: 'project exception rate limit window',
    per_issue_rate_limit_bucket_size_minutes: 'per-issue exception rate limit window',
}

function describeChange(change: ActivityChange): JSX.Element | null {
    if (change.field === 'autocapture_exceptions_opt_in') {
        return <>{change.after ? 'enabled' : 'disabled'} exception autocapture</>
    }
    if (change.field && change.field in RATE_LIMIT_LABELS) {
        const label = RATE_LIMIT_LABELS[change.field]
        return change.after == null ? (
            <>removed the {label}</>
        ) : (
            <>
                set the {label} to {String(change.after)}
            </>
        )
    }
    if (change.field && change.field in BUCKET_LABELS) {
        const label = BUCKET_LABELS[change.field]
        return change.after == null ? (
            <>removed the {label}</>
        ) : (
            <>
                set the {label} to {String(change.after)} minutes
            </>
        )
    }
    return null
}

export function errorTrackingSettingsActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    if (logItem.activity === 'updated') {
        const listParts = (logItem.detail?.changes ?? [])
            .map(describeChange)
            .filter((part): part is JSX.Element => part !== null)
        if (listParts.length) {
            return {
                description: (
                    <SentenceList
                        listParts={listParts}
                        prefix={<strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>}
                    />
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification, 'error tracking settings')
}
