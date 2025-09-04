import { connect, kea, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders/lib'
import { subscriptions } from 'kea-subscriptions/lib'

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

    loaders(() => ({
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
                    return {
                        mostProbableRelease: {
                            commitSha: '941be080cc022f64c10cf16025714eca48c29854',
                            repositoryUrl: 'http://example.com/first/second/third',
                            repositoryName: 'posthog-cli-github-action',
                            branch: 'main',
                        },
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
    mostProbableRelease: ExceptionRelease
    otherReleases: ExceptionRelease[]
}
