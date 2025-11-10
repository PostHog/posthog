import { connect, kea, path, props, selectors } from 'kea'

import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import 'lib/components/Errors/stackFrameLogic'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingRelease, ErrorTrackingStackFrame } from 'lib/components/Errors/types'
import { dayjs } from 'lib/dayjs'

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
                const relatedReleases: ErrorTrackingRelease[] = rawIds
                    .map((id) => stackFrameRecords[id]?.release)
                    .filter((r) => !!r) as ErrorTrackingRelease[]

                const uniqueRelatedReleasesIds = [...new Set(relatedReleases.map((r) => r?.id))]
                if (uniqueRelatedReleasesIds.length === 1) {
                    return relatedReleases[0]
                }
                const kaboomFrame = frames.reverse()[0]
                if (stackFrameRecords[kaboomFrame.raw_id]?.release) {
                    return stackFrameRecords[kaboomFrame.raw_id].release
                } else {
                    // get most recent release
                    const sortedReleases = relatedReleases.sort(
                        (a, b) => dayjs(b.timestamp).unix() - dayjs(a.timestamp).unix()
                    )
                    return sortedReleases[0]
                }
            },
        ],
    })),
])
