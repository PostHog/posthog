import { connect, kea, path, props, selectors } from 'kea'

import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import 'lib/components/Errors/stackFrameLogic'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
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
        values: [errorPropertiesLogic(props), ['frames'], stackFrameLogic, ['stackFrameRecords']],
    })),

    selectors(({ values }) => ({
        release: [
            (s) => [s.frames, s.stackFrameRecords],
            () => {
                const frames = values.frames as ErrorTrackingStackFrame[]
                const stackFrameRecords = values.stackFrameRecords

                const rawIds = frames.map((f) => f.raw_id)
                const relatedReleases = rawIds.map((id) => stackFrameRecords[id]?.release).filter((r) => Boolean(r))
                const uniqueRelatedReleasesIds = [...new Set(relatedReleases.map((r) => r?.id))]

                if (uniqueRelatedReleasesIds.length === 1) {
                    return relatedReleases[0]
                }

                const framesEnrichedWithReleases = frames.map((f) => ({
                    ...f,
                    release: stackFrameRecords[f.raw_id]?.release,
                }))

                const kaboomFrame = framesEnrichedWithReleases.reverse().find((f) => Boolean(f.release))

                return kaboomFrame?.release
            },
        ],
    })),
])
