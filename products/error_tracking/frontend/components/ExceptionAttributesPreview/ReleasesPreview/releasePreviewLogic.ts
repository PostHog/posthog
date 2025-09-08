import { connect, kea, path, props } from 'kea'
import { loaders } from 'kea-loaders/lib'

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
                loadRelease: async (dto: {
                    // we have exceptionReleases from the already loaded event. Cymbal enriches event with that data
                    exceptionReleases?: EventExceptionRelease[]
                }) => {
                    // we can't do anything if there are neither frames nor existing releases
                    if (!values.frames && !dto.exceptionReleases) {
                        return undefined
                    }

                    // if there is only one associated release, there is no need to look for the kaboom frame
                    // because we would find the same release anyways. This is a big performance win. I calculated
                    // how many events are related to how many releases and 95% events in the last 30 days are related to
                    // at most 1 release
                    if (dto.exceptionReleases?.length === 1) {
                        return dto.exceptionReleases[0]
                    }

                    // otherwise - this is a case where there are multiple releases associated with an error
                    // it means that individual stack frames are not all associated with the same release
                    // we need to find the most probable release by checking the frames

                    // if there are no frames, we can't load any releases
                    if (!values.frames || values.frames.length === 0) {
                        return undefined
                    }

                    const response: any = { results: {} }
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
