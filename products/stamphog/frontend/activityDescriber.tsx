import {
    ActivityChange,
    ActivityLogItem,
    Description,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'

import { ReviewModeEnumApi } from './generated/api.schemas'
import { REVIEW_MODE_LABELS } from './reviewModeLabels'

// A GitHub installation webhook writes a system row, so the actor reads "PostHog". Say which
// GitHub event caused it, or the reader cannot tell why reviews stopped.
const WEBHOOK_REASON: Record<string, string> = {
    removed: 'after GitHub removed it from the installation',
    deleted: 'after the GitHub app was uninstalled',
}

// Sentences leave out the repository name: it is appended once, after the whole list.
function repoConfigFieldCopy(change: ActivityChange): Description | null {
    switch (change.field) {
        case 'enabled':
            return change.after ? <>turned reviews on</> : <>turned reviews off</>
        case 'digest_enabled':
            return change.after ? <>turned the digest on</> : <>turned the digest off</>
        case 'review_mode': {
            const mode = String(change.after)
            return (
                <>
                    changed the review mode to <strong>{REVIEW_MODE_LABELS[mode as ReviewModeEnumApi] ?? mode}</strong>
                </>
            )
        }
        case 'trigger_label':
            return (
                <>
                    changed the trigger label to <strong>{String(change.after)}</strong>
                </>
            )
        case 'installation_id':
            return <>connected a new GitHub installation</>
        case 'connected_by_user_id':
            return <>became the connecting user</>
        default:
            return null
    }
}

export function stamphogRepoConfigActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    if (logItem.scope !== 'StamphogRepoConfig') {
        console.error('stamphog describer received a non-repo-config activity')
        return { description: null }
    }

    const actor = <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>
    const repository = <strong>{logItem.detail.name || 'a repository'}</strong>

    if (logItem.activity === 'created') {
        // A row created through the API has no installation until a sync binds it.
        const verb = logItem.detail.type === 'connected' ? 'connected' : 'added'
        return {
            description: (
                <>
                    {actor} {verb} {repository}
                </>
            ),
        }
    }

    const parts = (logItem.detail.changes || []).map(repoConfigFieldCopy).filter(Boolean) as Description[]
    if (logItem.activity !== 'updated' || parts.length === 0) {
        return defaultDescriber(logItem, asNotification, repository)
    }

    const webhookAction = logItem.detail.trigger?.payload?.action
    const reason = typeof webhookAction === 'string' ? WEBHOOK_REASON[webhookAction] : undefined
    return {
        description: (
            <SentenceList
                listParts={parts}
                prefix={actor}
                suffix={
                    <>
                        for {repository}
                        {reason ? ` ${reason}` : null}
                    </>
                }
            />
        ),
    }
}
