import type { ReactElement } from 'react'
import Svg, { Path } from 'react-native-svg'

import { useTheme } from '../theme'
import { LogomarkShapes } from './LogomarkShapes'
import { WORDMARK_PATH } from './wordmarkPath'

const VIEW_BOX_WIDTH = 160
const VIEW_BOX_HEIGHT = 28

const WHITE_LOGOMARK_PATH =
    'm50.02 23.34-.34-.04c-1-.13-1.95-.6-2.66-1.33L35.58 10.11a.5.5 0 0 0-.86.35V27.5c0 .28.22.5.5.5H49c1.48 0 2.67-1.2 2.67-2.67v-.1a1.9 1.9 0 0 0-1.66-1.9m-10.81.2a1.78 1.78 0 1 1 0-3.56 1.78 1.78 0 0 1 0 3.57M0 25.41A2.6 2.6 0 0 0 2.59 28h5.22a.5.5 0 0 0 .37-.84L.87 19.13a.5.5 0 0 0-.87.34zm18.81 1.74a.5.5 0 0 1-.36.85h-7.09a.5.5 0 0 1-.37-.17L8.94 25.5.13 15.82A.5.5 0 0 1 0 15.5V8.75a.5.5 0 0 1 .86-.34zM0 2.68C0 .28 2.92-.91 4.59.82l25.6 26.33a.5.5 0 0 1-.36.85h-7.76a.5.5 0 0 1-.37-.17l-2.1-2.33L.28 5.3A1 1 0 0 1 0 4.6zm10.74 0c0-2.4 2.92-3.59 4.59-1.87L32.5 18.48l.5.51v7.3a.5.5 0 0 1-.86.35l-1.12-1.14L11.3 5.23a2 2 0 0 1-.57-1.4zM33 7.46v7.8a.5.5 0 0 1-.85.36l-9.61-9.89a2 2 0 0 1-.57-1.4V2.69c0-2.4 2.92-3.59 4.59-1.86z'

interface PostHogLogoProps {
    height?: number
}

/** The landscape lockup: logomark plus wordmark. The brand guidelines forbid plain text beside the logomark. */
export function PostHogLogo({ height = 28 }: PostHogLogoProps): ReactElement {
    const { scheme, colors } = useTheme()
    const fill = scheme === 'dark' ? colors.white : colors.ink
    return (
        <Svg
            width={(height * VIEW_BOX_WIDTH) / VIEW_BOX_HEIGHT}
            height={height}
            viewBox={`0 0 ${VIEW_BOX_WIDTH} ${VIEW_BOX_HEIGHT}`}
            accessibilityRole="image"
            accessibilityLabel="PostHog"
        >
            {scheme === 'dark' ? <Path fill={fill} d={WHITE_LOGOMARK_PATH} /> : <LogomarkShapes />}
            <Path fill={fill} d={WORDMARK_PATH} />
        </Svg>
    )
}
