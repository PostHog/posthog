import type { ReactElement } from 'react'
import Svg, { Rect } from 'react-native-svg'

import { useColors } from '../theme'
import type { IconProps } from './types'

export function PauseIcon({ size = 16, color }: IconProps): ReactElement {
    const colors = useColors()
    return (
        <Svg width={size} height={size} viewBox="0 0 24 24" fill={color ?? colors.ink}>
            <Rect x={6} y={5} width={4} height={14} rx={1.2} />
            <Rect x={14} y={5} width={4} height={14} rx={1.2} />
        </Svg>
    )
}
