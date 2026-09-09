import { useActions, useValues } from 'kea'

import { IconCopy, IconShare } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import posthog from 'lib/posthog-typed'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { getCurrentPlayerTime } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { ObservationShareLogicProps, observationShareLogic } from './observationShareLogic'

function ObservationShareDialogContent(props: ObservationShareLogicProps): JSX.Element {
    const { shareUrl, includeTime, time, timeError } = useValues(observationShareLogic(props))
    const { setIncludeTime, setTime } = useActions(observationShareLogic(props))

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
                <div>
                    <b>Click the button below</b> to copy a link to this observation.
                </div>
                <div>Make sure the person you share it with has access to this PostHog project.</div>
            </div>
            <LemonButton
                type="secondary"
                fullWidth
                center
                sideIcon={<IconCopy />}
                onClick={() => {
                    posthog.capture('replay_vision_observation_link_copied', { with_timestamp: includeTime })
                    void copyToClipboard(shareUrl, 'observation link').catch((e) => posthog.captureException(e))
                }}
                title={shareUrl}
                disabledReason={timeError ?? undefined}
                data-attr="vision-observation-share-copy"
            >
                <span className="break-all">{shareUrl}</span>
            </LemonButton>
            <div className="flex gap-2 items-center">
                <LemonCheckbox
                    label="Start recording at"
                    checked={includeTime}
                    onChange={setIncludeTime}
                    data-attr="vision-observation-share-include-time"
                />
                <LemonInput
                    className="w-20"
                    placeholder="00:00"
                    value={time ?? ''}
                    onChange={setTime}
                    onFocus={() => setIncludeTime(true)}
                    fullWidth={false}
                    size="small"
                    status={timeError ? 'danger' : undefined}
                    data-attr="vision-observation-share-time"
                />
            </div>
            {timeError && <p className="text-danger text-xs m-0">{timeError}</p>}
        </div>
    )
}

/**
 * Shares the observation page itself, not only the recording — the reader lands on the model's verdict with
 * the recording already open at the moment being discussed.
 */
export function ObservationShareButton({
    observationId,
    sessionRecordingId,
    playerKey,
}: {
    observationId: string
    sessionRecordingId: string
    playerKey: string
}): JSX.Element {
    return (
        <LemonButton
            icon={<IconShare />}
            type="secondary"
            size="small"
            tooltip="Copy a link to this observation, starting the recording where you are"
            data-attr="vision-observation-share"
            onClick={() =>
                LemonDialog.open({
                    title: 'Share observation',
                    // Read at click time: the player keeps moving, and reading it earlier would re-render the page.
                    content: () => (
                        <ObservationShareDialogContent
                            observationId={observationId}
                            seconds={getCurrentPlayerTime({ playerKey, sessionRecordingId })}
                        />
                    ),
                    maxWidth: '30rem',
                    primaryButton: null,
                })
            }
        >
            Share
        </LemonButton>
    )
}
