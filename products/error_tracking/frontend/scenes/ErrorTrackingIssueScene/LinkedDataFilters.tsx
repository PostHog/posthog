import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconLive, IconRewindPlay } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Spinner, Toggle, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'
import { pluralize } from 'lib/utils/strings'

import type { LinkedDataKind } from '../../components/ExceptionCard/exceptionCardLogic'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { issueLinkedDataLogic } from './issueLinkedDataLogic'

const TOGGLE_LABELS: Record<LinkedDataKind, string> = {
    recording: 'Recording',
    logs: 'Logs',
}

const TOGGLE_ICONS: Record<LinkedDataKind, ReactNode> = {
    recording: <IconRewindPlay />,
    logs: <IconLive />,
}

const LINKED_DATA_NOUNS: Record<LinkedDataKind, string> = {
    recording: 'a recording',
    logs: 'linked logs',
}

export function LinkedDataFilters(): JSX.Element {
    const { issueId } = useValues(errorTrackingIssueSceneLogic)
    const { requestLinkedData } = useActions(issueLinkedDataLogic({ issueId }))
    const logsEnabled = useFeatureFlag('LOGS_IN_ERROR_TRACKING')

    useOnMountEffect(requestLinkedData)

    return (
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Only exceptions with</span>
            <LinkedDataToggle issueId={issueId} kind="recording" />
            {logsEnabled && <LinkedDataToggle issueId={issueId} kind="logs" />}
        </div>
    )
}

function LinkedDataToggle({ issueId, kind }: { issueId: string; kind: LinkedDataKind }): JSX.Element {
    const { linkedData, linkedDataLoading, requiredLinks } = useValues(issueLinkedDataLogic({ issueId }))
    const { setLinkRequired } = useActions(issueLinkedDataLogic({ issueId }))
    const pressed = requiredLinks.includes(kind)
    const linkedCount = linkedData?.[kind].exceptionCount ?? null
    const tooltip =
        linkedData === null
            ? `Looking for exceptions with ${LINKED_DATA_NOUNS[kind]}`
            : linkedCount === 0
              ? `None of this issue's exceptions in the selected date range have ${LINKED_DATA_NOUNS[kind]}`
              : `${linkedCount} of ${pluralize(linkedData.exceptionCount, 'exception')} in the selected date range ${
                    linkedCount === 1 ? 'has' : 'have'
                } ${LINKED_DATA_NOUNS[kind]}`

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Toggle
                        variant="outline"
                        size="sm"
                        pressed={pressed}
                        // Turning the filter off always works, so the user is never stuck with it.
                        disabled={!pressed && linkedCount === 0}
                        onPressedChange={(nextPressed) => setLinkRequired(kind, nextPressed)}
                        data-attr={`error-tracking-issue-filter-with-${kind}`}
                    />
                }
            >
                {TOGGLE_ICONS[kind]}
                {TOGGLE_LABELS[kind]}
                {linkedDataLoading && linkedData === null ? (
                    <Spinner className="size-3" />
                ) : (
                    <span className="tabular-nums text-muted-foreground">{linkedCount}</span>
                )}
            </TooltipTrigger>
            <TooltipContent>{tooltip}</TooltipContent>
        </Tooltip>
    )
}
