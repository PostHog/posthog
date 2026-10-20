import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconLive, IconRewindPlay } from '@posthog/icons'

import { DropdownMenuCheckboxItem, DropdownMenuGroup, DropdownMenuLabel, Spinner } from 'lib/ui/quill'

import type { ErrorTrackingLinkedDataKind } from '~/queries/schema/schema-general'

import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { issueLinkedDataLogic } from './issueLinkedDataLogic'
import { LINKED_DATA_FILTER_LABELS } from './linkedDataFilterLabels'

const ICONS: Record<ErrorTrackingLinkedDataKind, ReactNode> = {
    recording: <IconRewindPlay />,
    logs: <IconLive />,
}

const LINKED_DATA_NOUNS: Record<ErrorTrackingLinkedDataKind, string> = {
    recording: 'a recording',
    logs: 'linked logs',
}

export function LinkedDataFilterMenuItems(): JSX.Element {
    const { issueId } = useValues(errorTrackingIssueSceneLogic)
    const { linkedDataKinds } = useValues(issueLinkedDataLogic({ issueId }))

    return (
        <DropdownMenuGroup>
            <DropdownMenuLabel>Linked data</DropdownMenuLabel>
            {linkedDataKinds.map((kind) => (
                <LinkedDataFilterMenuItem key={kind} issueId={issueId} kind={kind} />
            ))}
        </DropdownMenuGroup>
    )
}

function LinkedDataFilterMenuItem({
    issueId,
    kind,
}: {
    issueId: string
    kind: ErrorTrackingLinkedDataKind
}): JSX.Element {
    const { summary, summaryLoading, requiredLinks } = useValues(issueLinkedDataLogic({ issueId }))
    const { setLinkRequired } = useActions(issueLinkedDataLogic({ issueId }))
    const checked = requiredLinks.includes(kind)
    const linkedCount = summary?.[kind] ?? null
    const noneLinked = !!linkedCount && linkedCount.complete && linkedCount.count === 0

    return (
        <DropdownMenuCheckboxItem
            checked={checked}
            closeOnClick
            onCheckedChange={(nextChecked) => setLinkRequired(kind, nextChecked)}
            // Removing the filter always works, so the user is never stuck with it.
            disabledReason={
                !checked && noneLinked
                    ? `None of this issue's exceptions in the selected date range have ${LINKED_DATA_NOUNS[kind]}`
                    : undefined
            }
            data-attr={`error-tracking-issue-filter-with-${kind}`}
        >
            {ICONS[kind]}
            {LINKED_DATA_FILTER_LABELS[kind]}
            <span className="ml-auto pl-4 tabular-nums text-muted-foreground">
                {summaryLoading && !summary ? (
                    <Spinner className="size-3" />
                ) : linkedCount ? (
                    `${linkedCount.count}${linkedCount.complete ? '' : '+'}`
                ) : null}
            </span>
        </DropdownMenuCheckboxItem>
    )
}
