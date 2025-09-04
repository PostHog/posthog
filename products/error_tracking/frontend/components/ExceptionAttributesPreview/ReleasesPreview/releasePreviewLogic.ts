import { connect, kea, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders/lib'
import { subscriptions } from 'kea-subscriptions/lib'

import api from 'lib/api'
import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingStackFrame, ExceptionRelease } from 'lib/components/Errors/types'

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

    connect((props: ErrorPropertiesLogicProps) => ({
        values: [errorPropertiesLogic(props), ['frames']],
    })),

    selectors({
        // todo:ab - actually compute the kaboom frame
        kaboomFrame: [
            (s) => [s.frames],
            (frames: ErrorTrackingStackFrame[]) => {
                const kaboomFrame = frames.findLast((frame) => frame.in_app && frame.resolved)

                return kaboomFrame
            },
        ],
    }),

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
                loadRelease: async () => {
                    await new Promise((resolve) => setTimeout(resolve, 1_000))

                    const rawId = values.kaboomFrame?.raw_id
                    if (rawId) {
                        try {
                            const response = await api.errorTracking.stackFrameReleaseMetadata([rawId])

                            const gitMeta = response.results[rawId].git

                            return {
                                mostProbableRelease: {
                                    commitSha: gitMeta.commit_id,
                                    repositoryUrl: gitMeta.repo_url,
                                    repositoryName: gitMeta.repo_name,
                                    branch: gitMeta.branch,
                                },
                                otherReleases: [],
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
        kaboomFrame: () => {
            actions.loadRelease()
        },
    })),
])

export interface ReleasePreviewOutput {
    mostProbableRelease?: ExceptionRelease
    otherReleases: ExceptionRelease[]
}
