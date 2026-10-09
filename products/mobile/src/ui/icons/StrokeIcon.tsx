import type { ReactElement, ReactNode } from 'react'
import Svg from 'react-native-svg'

import { colors } from '../tokens'

interface StrokeIconProps {
    size: number
    color?: string
    strokeWidth: number
    viewBox?: string
    width?: number
    height?: number
    children: ReactNode
}

export function StrokeIcon({
    size,
    color = colors.ink,
    strokeWidth,
    viewBox = '0 0 24 24',
    width,
    height,
    children,
}: StrokeIconProps): ReactElement {
    return (
        <Svg
            width={width ?? size}
            height={height ?? size}
            viewBox={viewBox}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeLinejoin="round"
        >
            {children}
        </Svg>
    )
}
