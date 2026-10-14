import type { ReactElement } from 'react'
import { Path, Rect } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function RecordingIcon({ size = 18, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Rect x={3} y={5.5} width={18} height={13} rx={3} />
            <Path d="M10.3 9.4v5.2l4.4-2.6z" />
        </StrokeIcon>
    )
}
