import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import type { errorTrackingVolumeSparklineLogicType } from './errorTrackingVolumeSparklineLogicType'
import type { SparklineDatum, SparklineEvent, VolumeSparklineHoverSelection } from './types'

export interface ErrorTrackingVolumeSparklineLogicProps {
    sparklineKey: string
}

export const errorTrackingVolumeSparklineLogic = kea<errorTrackingVolumeSparklineLogicType>([
    path((key) => [
        'products',
        'error_tracking',
        'components',
        'VolumeSparkline',
        'errorTrackingVolumeSparklineLogic',
        key,
    ]),
    props({} as ErrorTrackingVolumeSparklineLogicProps),
    key(({ sparklineKey }) => sparklineKey),

    actions({
        setHoveredBin: (payload: { index: number; datum: SparklineDatum } | null) => ({ payload }),
        setHoveredEvent: (payload: SparklineEvent<string> | null) => ({ payload }),
        setClickedSpike: (payload: { datum: SparklineDatum; clientX: number; clientY: number } | null) => ({
            payload,
        }),
    }),

    reducers({
        hoverSelection: [
            null as VolumeSparklineHoverSelection | null,
            {
                setHoveredBin: (_, { payload }): VolumeSparklineHoverSelection | null =>
                    payload == null ? null : { kind: 'bin', index: payload.index, datum: payload.datum },
                setHoveredEvent: (_, { payload }): VolumeSparklineHoverSelection | null =>
                    payload == null ? null : { kind: 'event', event: payload },
            },
        ],
        clickedSpike: [
            null as { datum: SparklineDatum; clientX: number; clientY: number } | null,
            {
                setClickedSpike: (_, { payload }) => payload,
            },
        ],
    }),

    selectors({
        hoveredIndex: [
            (s) => [s.hoverSelection],
            (sel: VolumeSparklineHoverSelection | null): number | null => (sel?.kind === 'bin' ? sel.index : null),
        ],
        hoveredDatum: [
            (s) => [s.hoverSelection],
            (sel: VolumeSparklineHoverSelection | null): SparklineDatum | null =>
                sel?.kind === 'bin' ? sel.datum : null,
        ],
        isBarHighlighted: [
            (s) => [s.hoverSelection],
            (sel: VolumeSparklineHoverSelection | null): boolean => sel?.kind === 'bin',
        ],
    }),
])
