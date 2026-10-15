import type { ReactElement } from 'react'
import { Circle, Path } from 'react-native-svg'

import { colors } from '../tokens'
import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function MailUnreadIcon({ size = 20, color = colors.ink, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            {/* The outline stops short of the top right corner, so the unread dot sits clear of it. */}
            <Path d="M13.5 5H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
            <Path d="m3 7.5 9 6 3.6-2.4" />
            <Circle cx={19} cy={5} r={3} fill={color} stroke="none" />
        </StrokeIcon>
    )
}
