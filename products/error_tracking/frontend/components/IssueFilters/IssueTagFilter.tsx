import { useActions, useValues } from 'kea'

import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { issueTagDefinitionsLogic } from './issueTagDefinitionsLogic'
import { IssueTagSelect } from './IssueTagSelect'

export function IssueTagFilter(): JSX.Element | null {
    const { issueTag } = useValues(issueQueryOptionsLogic)
    const { setIssueTag } = useActions(issueQueryOptionsLogic)
    const { issueTagDefinitions, issueTagDefinitionsLoading } = useValues(issueTagDefinitionsLogic)

    // With no tag to pick, because none is enabled or the list failed to load, the picker has nothing to offer.
    // A filter that is already set stays visible, so it can be cleared.
    if (!issueTagDefinitionsLoading && !issueTagDefinitions?.length && !issueTag) {
        return null
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
