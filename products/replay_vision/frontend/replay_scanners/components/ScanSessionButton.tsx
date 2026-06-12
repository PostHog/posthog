import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconPlay } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown/LemonDropdown'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { replayScannerLogic } from '../replayScannerLogic'

export function ScanSessionButton({ scannerId }: { scannerId: string }): JSX.Element {
    const { triggeringOnDemandObservation, onDemandObservationSuccessCount } = useValues(
        replayScannerLogic({ id: scannerId })
    )
    const { triggerOnDemandObservation } = useActions(replayScannerLogic({ id: scannerId }))
    const [open, setOpen] = useState(false)
    const [sessionId, setSessionId] = useState('')
    const lastSeenSuccessCount = useRef(onDemandObservationSuccessCount)

    useEffect(() => {
        if (onDemandObservationSuccessCount > lastSeenSuccessCount.current) {
            lastSeenSuccessCount.current = onDemandObservationSuccessCount
            setSessionId('')
            setOpen(false)
        }
    }, [onDemandObservationSuccessCount])

    const trimmed = sessionId.trim()
    const submit = (): void => {
        if (!trimmed || triggeringOnDemandObservation) {
            return
        }
        triggerOnDemandObservation(trimmed)
    }

    return (
        <LemonDropdown
            visible={open}
            onVisibilityChange={setOpen}
            closeOnClickInside={false}
            placement="bottom-end"
            overlay={
                <div className="w-80 p-2 space-y-2">
                    <div className="text-xs text-muted">Scan a session recording with this scanner.</div>
                    <div className="flex items-center gap-2">
                        <LemonInput
                            value={sessionId}
                            onChange={setSessionId}
                            onPressEnter={submit}
                            placeholder="Session recording ID"
                            size="small"
                            fullWidth
                            autoFocus
                            data-attr="vision-scanner-scan-session-input"
                        />
                        <AccessControlAction
                            resourceType={AccessControlResourceType.SessionRecording}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                size="small"
                                type="primary"
                                onClick={submit}
                                loading={triggeringOnDemandObservation}
                                disabledReason={!trimmed ? 'Paste a session ID first' : undefined}
                                data-attr="vision-scanner-scan-session-submit"
                            >
                                Scan
                            </LemonButton>
                        </AccessControlAction>
                    </div>
                </div>
            }
        >
            <LemonButton size="small" type="secondary" icon={<IconPlay />} data-attr="vision-scanner-scan-session-open">
                Scan session
            </LemonButton>
        </LemonDropdown>
    )
}
