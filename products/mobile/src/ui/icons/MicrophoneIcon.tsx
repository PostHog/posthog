import type { ReactElement } from 'react'
import { Path, Rect } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function MicrophoneIcon({ size = 20, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Rect x={9} y={2} width={6} height={12} rx={3} />
            <Path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4m-3 0h6" />
        </StrokeIcon>
    )
}
