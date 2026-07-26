import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { Spinner, SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    ErrorTrackingFingerprintSceneLogicProps,
    decodeFingerprintSegment,
    errorTrackingFingerprintSceneLogic,
    rawFingerprintPathSegment,
} from './errorTrackingFingerprintSceneLogic'

export const scene: SceneExport<ErrorTrackingFingerprintSceneLogicProps> = {
    component: ErrorTrackingFingerprintScene,
    logic: errorTrackingFingerprintSceneLogic,
    paramsToProps: ({ params: { fingerprint }, searchParams: { timestamp } }) => ({
        // Decode from the raw pathname, not the router's already-decodeURI'd `fingerprint` param —
        // decoding that a second time crashes on a literal `%` and mangles `%XX` fingerprints.
        fingerprint: decodeFingerprintSegment(
            rawFingerprintPathSegment(router.values.location.pathname) ?? fingerprint
        ),
        timestamp,
    }),
}

export function ErrorTrackingFingerprintScene(): JSX.Element {
    const { notFound, retries, resolvedFingerprintLoading } = useValues(errorTrackingFingerprintSceneLogic)
    const { retry } = useActions(errorTrackingFingerprintSceneLogic)

    // We couldn't resolve the issue within the retry window. Rather than dead-ending on the generic
    // "page not found" screen, keep the user moving: a recently captured error can still be finishing
    // ingestion, so offer a fresh attempt and a way back to the full issue list.
    if (notFound) {
        return (
            <div className="flex flex-col items-center justify-center gap-3 text-center h-full py-16">
                <h2 className="mb-0">We couldn't find this issue yet</h2>
                <p className="text-secondary max-w-md mb-0">
                    If the error was captured recently, it can take a few moments to finish processing. Try again in a
                    moment, or head back to all issues to find it.
                </p>
                <div className="flex gap-2">
                    <LemonButton type="primary" onClick={retry} loading={resolvedFingerprintLoading}>
                        Try again
                    </LemonButton>
                    <LemonButton type="secondary" to={urls.errorTracking()}>
                        Back to all issues
                    </LemonButton>
                </div>
            </div>
        )
    }

    // First lookup in flight: just a spinner. Only once a lookup has missed do we explain the wait,
    // since a recently captured error can still be working through ingestion. The scene redirects to
    // the issue as soon as it resolves.
    if (retries === 0) {
        return <SpinnerOverlay sceneLevel />
    }

    return (
        <div className="flex flex-col items-center justify-center gap-3 text-center h-full py-16">
            <Spinner className="text-3xl" />
            <h2 className="mb-0">Still looking for this issue</h2>
            <p className="text-secondary max-w-md mb-0">
                We couldn't find it yet, so we're still looking. If the error was captured recently, it can take a few
                moments to finish processing, and this page opens automatically once it's ready.
            </p>
        </div>
    )
}
