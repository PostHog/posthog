import { connect, kea, path, props, selectors } from 'kea'
import { loaders } from 'node_modules/kea-loaders/lib'
import { subscriptions } from 'node_modules/kea-subscriptions/lib'

import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingStackFrame } from 'lib/components/Errors/types'

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
        release: [
            'release' as string | null,
            {
                loadRelease: async () => {
                    await new Promise((resolve) => setTimeout(resolve, 1_000))
                    return values.kaboomFrame?.raw_id ?? 'unDEfiNeD'
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
