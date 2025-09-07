import { kea, path } from 'kea'
import { loaders } from 'kea-loaders/lib'

import api from 'lib/api'
import 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingStackFrame, ParsedEventExceptionRelease } from 'lib/components/Errors/types'
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
        release: [
            undefined as ParsedEventExceptionRelease | undefined,
            {
                loadRelease: async (dto: {
                    // we have exceptionReleases from the already loaded event. Cymbal enriches event with that data
                    exceptionReleases?: ParsedEventExceptionRelease[]
                    frames?: ErrorTrackingStackFrame[]
                }) => {
                    // we can't do anything if there are neither frames nor existing releases
                    if (!dto.frames && !dto.exceptionReleases) {
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
                    if (!dto.frames || dto.frames.length === 0) {
                        return undefined
                    }

                    const rawIds = dto.frames.map((f) => f.raw_id)
                    const response = await api.errorTracking.stackFrameReleaseMetadata(rawIds)
                    const resultMap = response.results || {}

                    // we reverse the list in order to pick the stack frame which is "the closest" to the error
                    const kaboomFrame = [...(dto.frames || [])].reverse().find((f) => resultMap[f.raw_id])

                    if (kaboomFrame) {
                        const relatedRelease = resultMap[kaboomFrame.raw_id]
                        return parseExceptionRelease(relatedRelease)
                    }

                    return undefined
                },
            },
        ],
    })),
])
