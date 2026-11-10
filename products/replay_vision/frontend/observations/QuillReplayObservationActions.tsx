import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ReplayVisionFeedbackButton } from '../components/ReplayVisionFeedbackButton'
import { QuillObservationNotesButton } from './QuillObservationNotesButton'
import { QuillObservationShareButton } from './QuillObservationShareButton'

export function QuillReplayObservationActions({
    previousUrl,
    nextUrl,
    neighborsPending,
    neighborsFiltered,
    observationId,
    sessionRecordingId,
    playerKey,
}: {
    previousUrl: string | undefined
    nextUrl: string | undefined
    neighborsPending: boolean
    neighborsFiltered: boolean
    observationId: string
    sessionRecordingId: string
    playerKey: string
}): JSX.Element {
    return (
        <>
            <Button
                variant="outline"
                loading={neighborsPending}
                render={previousUrl ? <LinkPrimitive to={previousUrl} /> : undefined}
                disabledReason={
                    previousUrl || neighborsPending
                        ? undefined
                        : neighborsFiltered
                          ? 'No previous observation matching your filters'
                          : 'No newer observation'
                }
                tooltip={
                    <>
                        {neighborsFiltered
                            ? 'Previous observation matching your filters'
                            : 'Previous (newer) observation for this scanner'}{' '}
                        <KeyboardShortcut k />
                    </>
                }
                data-attr="vision-observation-prev"
            >
                <IconArrowLeft />
                Previous
            </Button>
            <Button
                variant="outline"
                loading={neighborsPending}
                render={nextUrl ? <LinkPrimitive to={nextUrl} /> : undefined}
                disabledReason={
                    nextUrl || neighborsPending
                        ? undefined
                        : neighborsFiltered
                          ? 'No next observation matching your filters'
                          : 'No older observation'
                }
                tooltip={
                    <>
                        {neighborsFiltered
                            ? 'Next observation matching your filters'
                            : 'Next (older) observation for this scanner'}{' '}
                        <KeyboardShortcut j />
                    </>
                }
                data-attr="vision-observation-next"
            >
                Next
                <IconArrowRight />
            </Button>
            <QuillObservationNotesButton />
            <QuillObservationShareButton
                observationId={observationId}
                sessionRecordingId={sessionRecordingId}
                playerKey={playerKey}
            />
            <ReplayVisionFeedbackButton />
        </>
    )
}
