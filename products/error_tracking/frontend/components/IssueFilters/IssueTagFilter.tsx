import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { issueTagDefinitionsLogic } from './issueTagDefinitionsLogic'
import { IssueTagSelect } from './IssueTagSelect'

export function IssueTagFilter(): JSX.Element | null {
    const { issueTag } = useValues(issueQueryOptionsLogic)
    const { setIssueTag } = useActions(issueQueryOptionsLogic)
    const { issueTagDefinitions, issueTagDefinitionsLoading } = useValues(issueTagDefinitionsLogic)
    const { loadIssueTagDefinitions } = useActions(issueTagDefinitionsLogic)

    // A filter that is already set stays visible, so it can be cleared. A failed load leaves the definitions null,
    // and nothing else retries it while the list stays open.
    if (!issueTagDefinitionsLoading && !issueTagDefinitions?.length && !issueTag) {
        return issueTagDefinitions === null ? (
            <LemonButton
                size="small"
                type="secondary"
                data-attr="error-tracking-issue-tag-filter-reload"
                onClick={() => loadIssueTagDefinitions()}
            >
                Reload tags
            </LemonButton>
        ) : null
    }

    return (
        <IssueTagSelect
            definitions={issueTagDefinitions ?? []}
            loading={issueTagDefinitionsLoading}
            issueTag={issueTag}
            onChange={setIssueTag}
        />
    )
}
