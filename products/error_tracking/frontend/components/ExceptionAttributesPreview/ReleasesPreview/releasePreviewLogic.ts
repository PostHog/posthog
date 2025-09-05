import { connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders/lib'
import { subscriptions } from 'kea-subscriptions/lib'

import api from 'lib/api'
import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import 'lib/components/Errors/stackFrameLogic'
import { ExceptionReleaseGitMeta } from 'lib/components/Errors/types'

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
    props({} as ErrorPropertiesLogicProps),
    key((props) => {
        return props.id
    }),

    connect((props: ErrorPropertiesLogicProps) => ({
        values: [errorPropertiesLogic(props), ['frames']],
    })),

    loaders(({ values }) => ({
        releasePreviewData: [
            {
                mostProbableRelease: {
                    commitSha: 'unknown yet',
                    repositoryUrl: 'unknown yet',
                    repositoryName: 'unknown yet',
                    branch: 'unknown yet',
                },
                otherReleases: [],
            } as ReleasePreviewOutput,
            {
                loadRelease: async (releasesMeta?: ExceptionReleaseGitMeta[]) => {
                    if (releasesMeta?.length === 1) {
                        return {
                            mostProbableRelease: releasesMeta[0],
                            otherReleases: [],
                        }
                    }

                    const frames = values.frames || []
                    if (frames.length > 0) {
                        try {
                            const rawIds = frames.map((f) => f.raw_id)
                            const response = await api.errorTracking.stackFrameReleaseMetadata(rawIds)
                            const resultMap = response.results || {}

                            const selected = [...frames]
                                .reverse()
                                .find((f) => resultMap[f.raw_id] && resultMap[f.raw_id].git)

                            if (selected) {
                                const gitMeta = resultMap[selected.raw_id].git
                                return {
                                    mostProbableRelease: {
                                        commitSha: gitMeta.commit_id,
                                        repositoryUrl: resolveRemoteUrlWithCommitToLink(
                                            gitMeta.remote_url,
                                            gitMeta.commit_id
                                        ),
                                        repositoryName: gitMeta.repo_name,
                                        branch: gitMeta.branch,
                                    },
                                    otherReleases: [],
                                }
                            }
                        } catch (e) {
                            console.warn('raw_id_release_metadata failed', e)
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

    subscriptions(({ actions }) => ({
        frames: () => {
            actions.loadRelease()
        },
    })),
])

function resolveRemoteUrlWithCommitToLink(remoteUrl: string, commitSha: string): string {
    if (remoteUrlIsSsh(remoteUrl)) {
        const normalized = normalizeRemoteUrl(remoteUrl)

        return `${normalized}/commit/${commitSha}`
    }
    return remoteUrl
}

function remoteUrlIsSsh(remoteUrl: string): boolean {
    return remoteUrl.startsWith('git@')
}

function normalizeRemoteUrl(remoteUrl: string): string {
    if (!remoteUrlIsSsh(remoteUrl)) {
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

export interface ReleasePreviewOutput {
    mostProbableRelease?: ExceptionReleaseGitMeta
    otherReleases: ExceptionReleaseGitMeta[]
}
