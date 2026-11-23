import { useActions, useValues } from 'kea'

import { Button } from 'lib/ui/quill'

import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { issueTagDefinitionsLogic } from './issueTagDefinitionsLogic'
import { IssueTagSelect } from './IssueTagSelect'

export function IssueTagFilter(): JSX.Element | null {
    const { issueTags } = useValues(issueQueryOptionsLogic)
    const { setIssueTags, setIssueTagState } = useActions(issueQueryOptionsLogic)
    const { issueTagDefinitions, issueTagDefinitionsLoading } = useValues(issueTagDefinitionsLogic)
    const { loadIssueTagDefinitions } = useActions(issueTagDefinitionsLogic)

    // A filter that is already set stays visible, so it can be cleared. A failed load leaves the definitions null,
    // and nothing else retries it while the list stays open.
    if (!issueTagDefinitionsLoading && !issueTagDefinitions?.length && !issueTags) {
        return issueTagDefinitions === null ? (
            <Button
                variant="outline"
                size="default"
                data-attr="error-tracking-issue-tag-filter-reload"
                onClick={() => loadIssueTagDefinitions()}
            >
                Reload tags
            </Button>
        ) : null
    }

    return (
        <IssueTagSelect
            definitions={issueTagDefinitions ?? []}
            loading={issueTagDefinitionsLoading}
            issueTags={issueTags}
            onTagStateChange={setIssueTagState}
            onClear={() => setIssueTags(null)}
        />
    )
}
