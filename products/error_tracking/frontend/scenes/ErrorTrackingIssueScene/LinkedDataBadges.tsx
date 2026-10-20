import { useValues } from 'kea'

import { IconLive, IconRewindPlay } from '@posthog/icons'

import { ErrorEventType } from 'lib/components/Errors/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { issueLinkedDataLogic } from './issueLinkedDataLogic'

export function LinkedDataBadges({ record }: { record: ErrorEventType }): JSX.Element | null {
    const { issueId } = useValues(errorTrackingIssueSceneLogic)
    const { getEventLinkedData } = useValues(issueLinkedDataLogic({ issueId }))
    const logsEnabled = useFeatureFlag('LOGS_IN_ERROR_TRACKING')
    const linked = getEventLinkedData(record)

    if (!linked || (!linked.recording && !(logsEnabled && linked.logs))) {
        return null
    }

    return (
        <span className="inline-flex items-center gap-1 text-muted-foreground">
            {linked.recording && (
                <Tooltip>
                    <TooltipTrigger render={<span className="inline-flex" aria-label="Has a recording" />}>
                        <IconRewindPlay />
                    </TooltipTrigger>
                    <TooltipContent>Has a recording</TooltipContent>
                </Tooltip>
            )}
            {logsEnabled && linked.logs && (
                <Tooltip>
                    <TooltipTrigger render={<span className="inline-flex" aria-label="Has linked logs" />}>
                        <IconLive />
                    </TooltipTrigger>
                    <TooltipContent>Has linked logs</TooltipContent>
                </Tooltip>
            )}
        </span>
    )
}
