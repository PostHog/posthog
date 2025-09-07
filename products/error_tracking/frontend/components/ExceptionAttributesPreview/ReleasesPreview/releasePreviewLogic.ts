import { kea, path } from 'kea'
import { loaders } from 'kea-loaders/lib'

import api from 'lib/api'
import 'lib/components/Errors/stackFrameLogic'
import {
    ErrorTrackingStackFrame,
    ParsedEventExceptionRelease,
    RawEventExceptionRelease,
} from 'lib/components/Errors/types'
import { parseExceptionRelease } from 'lib/components/Errors/utils'

import type { releasePreviewLogicType } from './releasePreviewLogicType'

export const releasePreviewLogic = kea<releasePreviewLogicType>([
    path([
        'products',
        'error_tracking',
        'frontend',
        'components',
        'ExceptionAttributesPreview',
        'ReleasesPreview',
        'releasePreviewLogic',
    ]),

    loaders(() => ({
        releasePreviewData: [
            {
                mostProbableRelease: undefined,
                otherReleases: [],
            } as ReleasePreviewOutput,
            {
                loadRelease: async (dto: {
                    // we have gitReleasesMeta from the already loaded event. Cymbal enriches event with that data.
                    exceptionReleases?: ParsedEventExceptionRelease[]
                    frames?: ErrorTrackingStackFrame[]
                }) => {
                    // we can't do anything if there is neither frames nor existing gitReleasesMeta
                    if (!dto.frames && !dto.exceptionReleases) {
                        return {
                            mostProbableRelease: undefined,
                            otherReleases: [],
                        }
                    }

                    // if there is only one associated release, we just return it. No need to fetch anything extra. This will for sure be that release
                    if (dto.exceptionReleases?.length === 1) {
                        return {
                            mostProbableRelease: dto.exceptionReleases[0],
                            otherReleases: [],
                        }
                    }

                    // if there are no frames, we can't load any releases
                    if (!dto.frames || dto.frames.length === 0) {
                        return {
                            mostProbableRelease: undefined,
                            otherReleases: [],
                        }
                    }

                    const rawIds = dto.frames.map((f) => f.raw_id)
                    const response = await api.errorTracking.stackFrameReleaseMetadata(rawIds)
                    const resultMap: Record<string, RawEventExceptionRelease> = response.results || {}

                    // we reverse the list in order to pick the frame which is "the closest" to the error. We call this frame "kaboom frame".
                    const selectedFrame = [...(dto.frames || [])]
                        .reverse()
                        .find((f) => resultMap[f.raw_id] && resultMap[f.raw_id].metadata?.git)

                    if (selectedFrame) {
                        const relatedRelease = resultMap[selectedFrame.raw_id]
                        return {
                            mostProbableRelease: parseExceptionRelease(relatedRelease),
                            otherReleases: [],
                        }
                    }

                    return {
                        mostProbableRelease: undefined,
                        otherReleases: [],
                    }
                },
            },
        ],
    })),
])

export class ExceptionReleaseMetadataParser {
    static getViewCommitLink(release: ParsedEventExceptionRelease): string | undefined {
        const hasRemoteUrl = release.metadata?.git?.remoteUrl !== undefined
        const hasCommitId = release.metadata?.git?.commitId !== undefined

        return hasRemoteUrl && hasCommitId
            ? this.resolveRemoteUrlWithCommitToLink(release.metadata?.git?.remoteUrl, release.metadata?.git?.commitId)
            : undefined
    }

    static resolveRemoteUrlWithCommitToLink(remoteUrl: string, commitSha: string): string {
        if (ExceptionReleaseMetadataParser.remoteUrlIsSsh(remoteUrl)) {
            const normalized = ExceptionReleaseMetadataParser.normalizeRemoteUrl(remoteUrl)

            return `${normalized}/commit/${commitSha}`
        }
        return remoteUrl
    }

    static remoteUrlIsSsh(remoteUrl: string): boolean {
        return remoteUrl.startsWith('git@')
    }

    static normalizeRemoteUrl(remoteUrl: string): string {
        if (!ExceptionReleaseMetadataParser.remoteUrlIsSsh(remoteUrl)) {
            return remoteUrl
        }
        // git@github.com:user/repo.git
        // 1. provider: between 'git@' and ':'
        // 2. user: after ':' and before first '/'
        // 3. path: after first '/'
        // Compose: https://provider/user/path (strip .git if present)

        const atIdx = remoteUrl.indexOf('@')
        const colonIdx = remoteUrl.indexOf(':')
        if (atIdx === -1 || colonIdx === -1) {
            return remoteUrl
        }
        const provider = remoteUrl.slice(atIdx + 1, colonIdx)
        const afterColon = remoteUrl.slice(colonIdx + 1)
        const slashIdx = afterColon.indexOf('/')
        if (slashIdx === -1) {
            return remoteUrl
        }
        const user = afterColon.slice(0, slashIdx)
        let path = afterColon.slice(slashIdx + 1)
        if (path.endsWith('.git')) {
            path = path.slice(0, -4)
        }
        return `https://${provider}/${user}/${path}`
    }
}

export interface ReleasePreviewOutput {
    mostProbableRelease?: ParsedEventExceptionRelease
}
