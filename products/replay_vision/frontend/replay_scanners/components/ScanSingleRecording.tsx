import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconPlay } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditCount } from '../../utils/credits'
import { sessionIdFromInput } from '../../utils/sessionIdInput'
import { replayScannerLogic } from '../replayScannerLogic'

export function ScanSingleRecording({ scannerId }: { scannerId: string }): JSX.Element {
    const { scanner, triggeringOnDemandObservation, onDemandObservationSuccessCount } = useValues(
        replayScannerLogic({ id: scannerId })
    )
    const { triggerOnDemandObservation } = useActions(replayScannerLogic({ id: scannerId }))
    const [sessionId, setSessionId] = useState('')
    const lastSeenSuccessCount = useRef(onDemandObservationSuccessCount)
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner?.user_access_level)

    useEffect(() => {
        if (onDemandObservationSuccessCount > lastSeenSuccessCount.current) {
            lastSeenSuccessCount.current = onDemandObservationSuccessCount
            setSessionId('')
        }
    }, [onDemandObservationSuccessCount])

    const parsedId = sessionIdFromInput(sessionId)
    const submit = (): void => {
        if (!parsedId || triggeringOnDemandObservation) {
            return
        }
        triggerOnDemandObservation(parsedId)
    }
    const creditsPerScan = scanner?.credits_per_observation

    return (
        <div className="flex flex-col gap-5">
            <p className="text-muted text-sm m-0">
                Run this scanner on one recording right now, without waiting for the schedule. Paste its session ID or a
                link to the recording.
                {creditsPerScan != null && ` Each scan uses ${formatCreditCount(creditsPerScan)}.`}
            </p>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <LemonInput
                    value={sessionId}
                    onChange={setSessionId}
                    onPressEnter={submit}
                    placeholder="Session ID or recording link"
                    fullWidth
                    data-attr="vision-scanner-scan-session-input"
                />
                <LemonButton
                    type="primary"
                    icon={<IconPlay />}
                    onClick={submit}
                    loading={triggeringOnDemandObservation}
                    disabledReason={
                        editDisabledReason ??
                        (!sessionId.trim()
                            ? 'Paste a session ID or a recording link first'
                            : !parsedId
                              ? "This link doesn't point at a recording"
                              : undefined)
                    }
                    data-attr="vision-scanner-scan-session-submit"
                >
                    Scan recording
                </LemonButton>
            </div>
        </div>
    )
}
