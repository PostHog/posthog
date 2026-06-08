/**
 * Storybook preview — dark-mode toggle (built-in v10 globalTypes) + a
 * decorator that wraps every story in the same background + text-color
 * the Next.js app uses.
 *
 * Also bootstraps MSW. Storybook is the ONLY surface that runs MSW; the
 * Next.js app surface is unaware of it (the app calls real REST endpoints
 * via the typed apiClient and stays bound to the production contract).
 * Stories that exercise the apiClient — e.g. AppShell + the
 * focus-with-mutation flow — go through these handlers.
 */

import './storybook.css'

import type { Preview } from '@storybook/react-vite'
import React, { useEffect, useState } from 'react'

import { worker } from './mocks/browser'

const mswPromise: Promise<unknown> =
    typeof window === 'undefined'
        ? Promise.resolve()
        : worker.start({
              onUnhandledRequest: 'bypass',
              serviceWorker: { url: '/mockServiceWorker.js' },
              quiet: true,
          })

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
    },
    // Built-in v10 globalType toggle replaces `storybook-dark-mode`.
    globalTypes: {
        theme: {
            name: 'Theme',
            description: 'Light / dark theme',
            defaultValue: 'light',
            toolbar: {
                icon: 'circlehollow',
                items: [
                    { value: 'light', icon: 'sun', title: 'Light' },
                    { value: 'dark', icon: 'moon', title: 'Dark' },
                ],
                dynamicTitle: true,
            },
        },
    },
    decorators: [
        (Story, context) => {
            const isDark = context.globals.theme === 'dark'
            useEffect(() => {
                document.documentElement.classList.toggle('dark', isDark)
                if (isDark) {
                    document.documentElement.setAttribute('theme', 'dark')
                } else {
                    document.documentElement.removeAttribute('theme')
                }
            }, [isDark])
            return (
                <MswGate>
                    <div className="min-h-full bg-background text-foreground">
                        <Story />
                    </div>
                </MswGate>
            )
        },
    ],
}

export default preview
