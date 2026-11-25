import { useDocumentTheme } from '@modelcontextprotocol/ext-apps/react'
import type { ReactElement } from 'react'

import { Logo } from '@posthog/brand/logo'

export function PostHogLogo({ size = 16 }: { size?: number }): ReactElement {
    const theme = useDocumentTheme()

    // The gradient logomark paints the hedgehog head in a fixed near-black, which disappears on a
    // dark host, so dark hosts get the single-color mark in white instead.
    if (theme === 'dark') {
        return <Logo.Logomark size={size} variant="mono" color="white" />
    }

    return <Logo.Logomark size={size} />
}
