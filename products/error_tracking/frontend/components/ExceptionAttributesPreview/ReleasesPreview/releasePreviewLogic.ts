import { connect, kea, path, props, selectors } from 'kea'
import { loaders } from 'node_modules/kea-loaders/lib'
import { subscriptions } from 'node_modules/kea-subscriptions/lib'

import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'

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

    connect((props: ErrorPropertiesLogicProps) => {
        return {
            values: [errorPropertiesLogic(props), ['frames']],
        }
    }),

    selectors({
        // todo:ab - actually compute the kaboom frame
        kaboomFrame: [
            (s) => [s.frames],
            (frames) => {
                return frames[0]
            },
        ],
    }),

    loaders(({ values }) => ({
        release: [
            'release' as string | null,
            {
                loadRelease: async () => {
                    await new Promise((resolve) => setTimeout(resolve, 1_000))
                    return values.release + ' updated'
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
