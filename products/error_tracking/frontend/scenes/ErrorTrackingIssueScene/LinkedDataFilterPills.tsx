import { useActions, useValues } from 'kea'

import { Chip, ChipClose } from 'lib/ui/quill'

import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { issueLinkedDataLogic } from './issueLinkedDataLogic'
import { LINKED_DATA_FILTER_LABELS } from './linkedDataFilterLabels'

export function LinkedDataFilterPills(): JSX.Element {
    const { issueId } = useValues(errorTrackingIssueSceneLogic)
    const { requiredLinks } = useValues(issueLinkedDataLogic({ issueId }))
    const { setLinkRequired } = useActions(issueLinkedDataLogic({ issueId }))

    return (
        <>
            {requiredLinks.map((kind) => (
                <Chip key={kind} data-attr={`error-tracking-issue-filter-pill-${kind}`}>
                    {LINKED_DATA_FILTER_LABELS[kind]}
                    <ChipClose
                        aria-label={`Remove filter: ${LINKED_DATA_FILTER_LABELS[kind]}`}
                        onClick={() => setLinkRequired(kind, false)}
                    />
                </Chip>
            ))}
        </>
    )
}
