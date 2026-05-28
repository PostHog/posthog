/**
 * Storybook preview — Quill ThemeSync + a decorator that wraps every story
 * in the same background + text-color the Next.js app uses.
 *
 * Mirrors the shape of `packages/quill/apps/storybook/.storybook/preview.tsx`
 * so design iteration in either Storybook feels identical.
 */

import './storybook.css'

import type { Preview } from '@storybook/react'
import { themes } from '@storybook/theming'
import React, { useEffect } from 'react'
import { useDarkMode } from 'storybook-dark-mode'

function ThemeSync({ children }: { children: React.ReactNode }): React.ReactElement {
    const isDark = useDarkMode()

    useEffect(() => {
        document.documentElement.classList.toggle('dark', isDark)
        if (isDark) {
            document.documentElement.setAttribute('theme', 'dark')
        } else {
            document.documentElement.removeAttribute('theme')
        }
    }, [isDark])

    return <>{children}</>
}

const preview: Preview = {
    parameters: {
        controls: {
            matchers: {
                color: /(background|color)$/i,
                date: /Date$/i,
            },
        },
        darkMode: {
            stylePreview: true,
            light: { ...themes.light, appBg: '#ffffff' },
            dark: { ...themes.dark, appBg: '#0a0a0a' },
        },
    },
    decorators: [
        (Story) => (
            <ThemeSync>
                <div className="min-h-full bg-background text-foreground">
                    <Story />
                </div>
            </ThemeSync>
        ),
    ],
}

export default preview
