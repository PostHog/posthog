import type { ReactElement } from 'react'
import { LogomarkShapes } from './LogomarkShapes'

interface PostHogLogomarkProps {
    height?: number
}

export function PostHogLogomark({ height = 18 }: PostHogLogomarkProps): ReactElement {
    return <LogomarkShapes height={height} accessibilityRole="image" accessibilityLabel="PostHog" />
}
