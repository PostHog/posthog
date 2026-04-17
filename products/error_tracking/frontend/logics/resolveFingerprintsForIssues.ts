import api from 'lib/api'
import { ErrorTrackingFingerprint } from 'lib/components/Errors/types'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'

/**
 * Resolve fingerprints for a set of issue ids.
 *
 * If the issue detail scene logic is already mounted for an id and has loaded
 * fingerprints, reuse them. Otherwise fall back to the existing paginated
 * `/fingerprints?issue_id=X` endpoint (one request per issue, in parallel).
 */
export async function resolveFingerprintsForIssues(
    issueIds: Array<ErrorTrackingIssue['id']>
): Promise<Record<string, string[]>> {
    const unique = Array.from(new Set(issueIds))
    const result: Record<string, string[]> = {}

    const toFetch: string[] = []
    for (const id of unique) {
        const mounted = errorTrackingIssueSceneLogic.findMounted({ id })
        const loaded = mounted?.values.issueFingerprints
        if (mounted && Array.isArray(loaded) && loaded.length > 0) {
            result[id] = loaded.map((f) => f.fingerprint)
        } else {
            toFetch.push(id)
        }
    }

    if (toFetch.length > 0) {
        const responses = await Promise.all(
            toFetch.map((id) =>
                api.errorTracking.fingerprints
                    .list(id)
                    .then((rows: ErrorTrackingFingerprint[]) => [id, rows.map((r) => r.fingerprint)] as const)
                    .catch(() => [id, [] as string[]] as const)
            )
        )
        for (const [id, fingerprints] of responses) {
            result[id] = fingerprints
        }
    }

    return result
}
