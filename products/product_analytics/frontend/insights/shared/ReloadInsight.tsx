import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { parseDraftQueryFromLocalStorage } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Node } from '~/queries/schema/schema-general'

export function ReloadInsight(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { reportInsightDraftRestored } = useActions(eventUsageLogic)
    const draftQueryLocalStorage = localStorage.getItem(`draft-query-${currentTeamId}`)
    let draftQuery: { query: Node<Record<string, any>>; timestamp: number } | null = null
    if (draftQueryLocalStorage) {
        const parsedQuery = parseDraftQueryFromLocalStorage(draftQueryLocalStorage)
        if (parsedQuery) {
            draftQuery = parsedQuery
        } else {
            localStorage.removeItem(`draft-query-${currentTeamId}`)
        }
    }

    if (!draftQuery?.query) {
        return <> </>
    }
    const draftTimestamp = draftQuery.timestamp
    return (
        <div className="text-secondary">
            You have an unsaved insight from {new Date(draftTimestamp).toLocaleString()}.{' '}
            <Link
                to={urls.insightNew({ query: draftQuery.query })}
                onClick={() =>
                    reportInsightDraftRestored(
                        'insight_editor',
                        Math.max(0, Math.round((Date.now() - draftTimestamp) / 1000))
                    )
                }
            >
                Click here
            </Link>{' '}
            to view it.
        </div>
    )
}
