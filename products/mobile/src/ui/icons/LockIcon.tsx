import type { ReactElement } from 'react'
import { Path, Rect } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function LockIcon({ size = 26, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Rect x={6} y={10.5} width={12} height={9.5} rx={2} />
            <Path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" />
        </StrokeIcon>
    )
}
