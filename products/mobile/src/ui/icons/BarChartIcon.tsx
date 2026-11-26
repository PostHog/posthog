import type { ReactElement } from 'react'
import Svg, { Rect } from 'react-native-svg'

import type { BarLayout } from '@/ui/chart/types'
import { useColors } from '@/ui/theme'

import type { IconProps } from './types'

export function BarChartIcon({ layout, size = 20, color }: IconProps & { layout: BarLayout }): ReactElement {
    const colors = useColors()
    return (
        <Svg width={size} height={size} viewBox="0 0 24 24" fill={color ?? colors.ink}>
            {layout === 'stacked' ? (
                <>
                    <Rect x={3} y={4} width={7} height={7} rx={1} />
                    <Rect x={3} y={13} width={7} height={7} rx={1} />
                    <Rect x={14} y={8} width={7} height={5} rx={1} />
                    <Rect x={14} y={15} width={7} height={5} rx={1} />
                </>
            ) : (
                <>
                    <Rect x={3} y={8} width={3} height={12} rx={1} />
                    <Rect x={7} y={13} width={3} height={7} rx={1} />
                    <Rect x={14} y={4} width={3} height={16} rx={1} />
                    <Rect x={18} y={10} width={3} height={10} rx={1} />
                </>
            )}
        </Svg>
    )
}
