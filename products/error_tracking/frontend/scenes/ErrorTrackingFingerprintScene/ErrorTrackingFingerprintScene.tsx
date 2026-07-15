import { useValues } from 'kea'
import { router } from 'kea-router'

import { NotFound } from 'lib/components/NotFound'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

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
    const { resolvedFingerprint, resolvedFingerprintLoading } = useValues(errorTrackingFingerprintSceneLogic)

    if (!resolvedFingerprint && !resolvedFingerprintLoading) {
        return <NotFound object="issue" />
    }

    return <SpinnerOverlay sceneLevel />
}
