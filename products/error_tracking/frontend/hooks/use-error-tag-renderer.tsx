import { useValues } from 'kea'
import { useCallback } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { ErrorEventType } from 'lib/components/Errors/types'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'

export interface ExceptionTagProps {
    label: string
    color: 'yellow' | 'red' | 'blue'
}

const tagColor = {
    yellow: 'bg-brand-yellow',
    red: 'bg-brand-red',
    blue: 'bg-brand-blue',
}

export function ExceptionTag({ color, label }: ExceptionTagProps): JSX.Element {
    return (
        <LemonTag
            size="small"
            className={cn(
                'font-semibold text-white border-gray-100/20 px-1 py-[0.1rem] text-[11px] rounded-sm inline',
                tagColor[color]
            )}
        >
            {label}
        </LemonTag>
    )
}

export function useErrorTagRenderer(): (evt: ErrorEventType | null) => JSX.Element {
    const { lastSeen, firstSeen, selectedEvent } = useValues(errorTrackingIssueSceneLogic)
    return useCallback(
        (evt: ErrorEventType | null) => {
            if (!evt) {
                return <></>
            }
            if (lastSeen && evt.timestamp && dayjs(evt.timestamp).isSame(lastSeen)) {
                return <ExceptionTag color="red" label="Last Seen" />
            }
            if (firstSeen && evt.timestamp && dayjs(evt.timestamp).isSame(firstSeen)) {
                return <ExceptionTag color="blue" label="First Seen" />
            }
            if (selectedEvent && selectedEvent.uuid == evt.uuid) {
                return <ExceptionTag color="yellow" label="Current" />
            }
            return <></>
        },
        [lastSeen, firstSeen, selectedEvent]
    )
}
