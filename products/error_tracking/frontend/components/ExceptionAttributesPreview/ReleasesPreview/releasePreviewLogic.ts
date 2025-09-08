import { connect, kea, path, props } from 'kea'
import { loaders } from 'kea-loaders/lib'

import api from 'lib/api'
import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import 'lib/components/Errors/stackFrameLogic'
import { EventExceptionRelease } from 'lib/components/Errors/types'

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

    loaders(({ values }) => ({
        release: [
            undefined as EventExceptionRelease | undefined,
            {
                loadRelease: async (exceptionReleases?: EventExceptionRelease[]) => {
                    if (!values.frames && !exceptionReleases) {
                        return undefined
                    }

                    if (exceptionReleases?.length === 1) {
                        return exceptionReleases[0]
                    }

                    if (!values.frames || values.frames.length === 0) {
                        return undefined
                    }

                    const rawIds = values.frames.map((f) => f.raw_id)
                    const response = await api.errorTracking.stackFrameReleaseMetadata(rawIds)

                    const resultMap = response.results || {}

                    // we reverse the list in order to pick the stack frame which is "the closest" to the error
                    const kaboomFrame = values.frames.reverse().find((f) => resultMap[f.raw_id])

                    if (kaboomFrame) {
                        const relatedRelease = resultMap[kaboomFrame.raw_id]
                        return relatedRelease
                    }

                    return undefined
                },
            },
        ],
    })),
])
