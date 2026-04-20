import { connect, kea, path, props, selectors } from 'kea'

import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorTrackingRelease } from 'lib/components/Errors/types'
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
        values: [errorPropertiesLogic(props), ['frames', 'stackFrameRecords']],
    })),

    selectors(() => ({
        release: [
            (s) => [s.frames, s.stackFrameRecords],
            (frames, stackFrameRecords) => {
                if (!frames.length || Object.keys(stackFrameRecords).length === 0) {
                    return undefined
                }
                const rawIds = frames.map((f) => f.raw_id)
                const relatedReleases: ErrorTrackingRelease[] = rawIds
                    .map((id) => stackFrameRecords[id]?.release)
                    .filter((r) => !!r) as ErrorTrackingRelease[]

                const uniqueRelatedReleasesIds = [...new Set(relatedReleases.map((r) => r?.id))]
                if (uniqueRelatedReleasesIds.length === 1) {
                    return relatedReleases[0]
                }
                const kaboomFrame = frames.reverse()[0]
                if (stackFrameRecords[kaboomFrame?.raw_id]?.release) {
                    return stackFrameRecords[kaboomFrame.raw_id].release
                }
                // get most recent release
                const sortedReleases = relatedReleases.sort(
                    (a, b) => dayjs(b.created_at).unix() - dayjs(a.created_at).unix()
                )
                return sortedReleases[0]
            },
        ],
    })),
])
