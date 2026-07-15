import { events, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { errorTrackingFingerprintsResolveRetrieve } from '../../generated/api'
import type { ErrorTrackingFingerprintApi } from '../../generated/api.schemas'
import type { errorTrackingFingerprintSceneLogicType } from './errorTrackingFingerprintSceneLogicType'

export interface ErrorTrackingFingerprintSceneLogicProps {
    fingerprint: string
    timestamp?: string
}

// kea-router runs decodeURI(pathname) before matching the route, so the `:fingerprint` param it
// hands paramsToProps is already partially decoded. Decoding that a second time turns an encoded
// literal `%` into a bare `%` (throwing URIError) and silently mangles `%XX` sequences. Callers
// must pass the raw, still-percent-encoded path segment (see rawFingerprintPathSegment); we decode
// it exactly once here and fall back to the raw text if it isn't valid encoding.
export function decodeFingerprintSegment(rawSegment: string): string {
    try {
        return decodeURIComponent(rawSegment)
    } catch {
        return rawSegment
    }
}

// Recover the original encoded fingerprint segment from the raw pathname. kea-router keeps
// location.pathname percent-encoded — only the transient match inside urlToAction runs decodeURI —
// so this is the single source that survives one clean decodeURIComponent.
export function rawFingerprintPathSegment(pathname: string): string | null {
    const match = pathname.match(/\/error_tracking\/fingerprint\/([^/]+)\/?$/)
    return match ? match[1] : null
}

export const errorTrackingFingerprintSceneLogic = kea<errorTrackingFingerprintSceneLogicType>([
    path((key) => ['products', 'error_tracking', 'scenes', 'errorTrackingFingerprintSceneLogic', key]),
    props({} as ErrorTrackingFingerprintSceneLogicProps),
    key((props) => props.fingerprint),

    loaders(({ props }) => ({
        resolvedFingerprint: [
            null as ErrorTrackingFingerprintApi | null,
            {
                resolveFingerprint: async (): Promise<ErrorTrackingFingerprintApi | null> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId || !props.fingerprint) {
                        return null
                    }
                    return await errorTrackingFingerprintsResolveRetrieve(String(teamId), {
                        fingerprint: props.fingerprint,
                    })
                },
            },
        ],
    })),

    listeners(({ props }) => ({
        resolveFingerprintSuccess: ({ resolvedFingerprint }) => {
            if (!resolvedFingerprint) {
                return
            }
            router.actions.replace(
                urls.errorTrackingIssue(resolvedFingerprint.issue_id, {
                    fingerprint: props.fingerprint,
                    timestamp: props.timestamp ?? resolvedFingerprint.first_seen ?? undefined,
                })
            )
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.resolveFingerprint()
        },
    })),
])
