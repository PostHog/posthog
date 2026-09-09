import { useActions, useValues } from 'kea'

import * as handClaspPng from '@posthog/brand/hoggies/png/hand-clasp'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ErrorTrackingRuntime } from 'lib/components/Errors/types'

import { missingReleaseIdModalLogic } from './missingReleaseIdModalLogic'

const HedgehogHandClasp = pngHoggie(handClaspPng)

interface SdkRequirement {
    packageName: string
    version: string
}

// The first SDK version that reports `$release_id` on exceptions (PostHog/posthog-js#4308).
const SDK_REQUIREMENT_BY_RUNTIME: Partial<Record<ErrorTrackingRuntime, SdkRequirement>> = {
    web: { packageName: 'posthog-js', version: '1.409.0' },
    node: { packageName: 'posthog-node', version: '5.47.0' },
}

export interface MissingReleaseIdModalProps {
    eventId: string
    runtime?: ErrorTrackingRuntime
}

export function MissingReleaseIdModal({ eventId, runtime }: MissingReleaseIdModalProps): JSX.Element {
    const { isModalOpen } = useValues(missingReleaseIdModalLogic({ eventId }))
    const { closeModal } = useActions(missingReleaseIdModalLogic({ eventId }))
    const sdk = runtime ? SDK_REQUIREMENT_BY_RUNTIME[runtime] : undefined

    return (
        <LemonModal isOpen={isModalOpen} onClose={closeModal} simple width={480}>
            <div className="flex flex-col items-center gap-2.5 p-6 text-center">
                <HedgehogHandClasp className="block w-auto mx-auto h-28" />
                <h2 className="m-0 text-2xl font-bold">Update your SDK to attach releases</h2>
                <p className="m-0 text-secondary text-pretty">
                    We recently changed how releases work. The CLI now injects a release id into your build, and the SDK
                    sends it with every exception. Both need to be up to date.
                </p>
                <p className="m-0 text-secondary text-pretty">
                    It looks like you updated only the CLI. This exception came from a build the new CLI processed, but
                    the SDK did not report a release id.
                </p>
                <p className="m-0 text-pretty">
                    {sdk ? (
                        <>
                            Update <strong>{sdk.packageName}</strong> to version <strong>{sdk.version}</strong> or
                            later, then deploy again.
                        </>
                    ) : (
                        <>Update your PostHog SDK to the latest version, then deploy again.</>
                    )}
                </p>
                <LemonButton
                    type="primary"
                    onClick={closeModal}
                    className="mt-2"
                    data-attr="error-tracking-missing-release-id-modal-close"
                >
                    Got it
                </LemonButton>
            </div>
        </LemonModal>
    )
}
