/**
 * Storybook preview — Quill ThemeSync + a decorator that wraps every story
 * in the same background + text-color the Next.js app uses.
 *
 * Also bootstraps MSW. Storybook is the ONLY surface that runs MSW; the
 * Next.js app surface is unaware of it (the app calls real REST endpoints
 * via the typed apiClient and stays bound to the production contract).
 * Stories that exercise the apiClient — e.g. AppShell + the
 * focus-with-mutation flow — go through these handlers.
 *
 * Mirrors the shape of `packages/quill/apps/storybook/.storybook/preview.tsx`
 * so design iteration in either Storybook feels identical.
 */

import './storybook.css'

import type { Preview } from '@storybook/react'
import { themes } from '@storybook/theming'
import React, { useEffect, useState } from 'react'
import { useDarkMode } from 'storybook-dark-mode'

import { worker } from './mocks/browser'

const mswPromise: Promise<unknown> =
    typeof window === 'undefined'
        ? Promise.resolve()
        : worker.start({
              onUnhandledRequest: 'bypass',
              serviceWorker: { url: '/mockServiceWorker.js' },
              quiet: true,
          })

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

function MswGate({ children }: { children: React.ReactNode }): React.ReactElement | null {
    const [ready, setReady] = useState(false)
    useEffect(() => {
        let cancelled = false
        void mswPromise.then(() => {
            if (!cancelled) {
                setReady(true)
            }
        })
        return () => {
            cancelled = true
        }
    }, [])
    if (!ready) {
        return null
    }
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
        // Sidebar order — the whole-shell stories are the primary review
        // surface so they come first; per-component stories are scaffolding
        // for that surface; the embeddable chat package is its own thing.
        options: {
            storySort: {
                order: ['Agent console', 'Agent console components', 'Agent Chat'],
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
            <MswGate>
                <ThemeSync>
                    <div className="min-h-full bg-background text-foreground">
                        <Story />
                    </div>
                </ThemeSync>
            </MswGate>
        ),
    ],
}

export default preview
