import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconLive, IconRewindPlay } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { DropdownMenuCheckboxItem, DropdownMenuGroup, DropdownMenuLabel, Spinner } from 'lib/ui/quill'

import type { LinkedDataKind } from '../../components/ExceptionCard/exceptionCardLogic'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { issueLinkedDataLogic } from './issueLinkedDataLogic'
import { LINKED_DATA_FILTER_LABELS } from './linkedDataFilterLabels'

const ICONS: Record<LinkedDataKind, ReactNode> = {
    recording: <IconRewindPlay />,
    logs: <IconLive />,
}

const LINKED_DATA_NOUNS: Record<LinkedDataKind, string> = {
    recording: 'a recording',
    logs: 'linked logs',
}

export function LinkedDataFilterMenuItems(): JSX.Element {
    const { issueId } = useValues(errorTrackingIssueSceneLogic)
    const logsEnabled = useFeatureFlag('LOGS_IN_ERROR_TRACKING')

    return (
        <DropdownMenuGroup>
            <DropdownMenuLabel>Linked data</DropdownMenuLabel>
            <LinkedDataFilterMenuItem issueId={issueId} kind="recording" />
            {logsEnabled && <LinkedDataFilterMenuItem issueId={issueId} kind="logs" />}
        </DropdownMenuGroup>
    )
}

function LinkedDataFilterMenuItem({ issueId, kind }: { issueId: string; kind: LinkedDataKind }): JSX.Element {
    const { linkedData, linkedDataLoading, requiredLinks } = useValues(issueLinkedDataLogic({ issueId }))
    const { setLinkRequired } = useActions(issueLinkedDataLogic({ issueId }))
    const checked = requiredLinks.includes(kind)
    const linkedCount = linkedData?.[kind].exceptionCount ?? null

    return (
        <DropdownMenuCheckboxItem
            checked={checked}
            closeOnClick
            onCheckedChange={(nextChecked) => setLinkRequired(kind, nextChecked)}
            // Removing the filter always works, so the user is never stuck with it.
            disabledReason={
                !checked && linkedCount === 0
                    ? `None of this issue's exceptions in the selected date range have ${LINKED_DATA_NOUNS[kind]}`
                    : undefined
            }
            data-attr={`error-tracking-issue-filter-with-${kind}`}
        >
            {ICONS[kind]}
            {LINKED_DATA_FILTER_LABELS[kind]}
            <span className="ml-auto pl-4 tabular-nums text-muted-foreground">
                {linkedDataLoading && linkedData === null ? <Spinner className="size-3" /> : linkedCount}
            </span>
        </DropdownMenuCheckboxItem>
    )
}
