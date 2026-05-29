import '../src/styles/globals.css'

import type { Metadata, Viewport } from 'next'

import { AppShell } from '@/components/AppShell'

export const metadata: Metadata = {
    title: 'Agent console — PostHog',
    description: 'Read-mostly console for the PostHog agent platform.',
}

export const viewport: Viewport = {
    themeColor: [
        { media: '(prefers-color-scheme: light)', color: '#ffffff' },
        { media: '(prefers-color-scheme: dark)', color: '#0a0a0a' },
    ],
}

/**
 * Pre-hydrate theme bootstrap. Reads the same `localStorage` key
 * Quill's `ThemeProvider` writes to (default: `theme`), falls back
 * to the OS preference, and stamps `<html data-theme="...">` before
 * React renders. Without this the first paint always uses the SSR
 * default (light) before Quill swaps to dark on mount — a visible
 * flash. If we ever pass a custom `storageKey` to `<ThemeProvider>`,
 * mirror it here.
 */
const THEME_BOOTSTRAP = `(() => {
    try {
        var pref = localStorage.getItem('theme');
        var sysDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        var theme = pref === 'dark' || pref === 'light' ? pref : (sysDark ? 'dark' : 'light');
        document.documentElement.setAttribute('data-theme', theme);
    } catch (_) {}
})();`

export default function RootLayout({ children }: { children: React.ReactNode }): React.ReactElement {
    return (
        // The pre-hydrate THEME_BOOTSTRAP script below stamps `data-theme`
        // on this element before React mounts, so the SSR'd HTML (no
        // attribute) and the live DOM (`data-theme="dark"` etc.) won't
        // match. `suppressHydrationWarning` here scopes the suppression
        // to the `<html>` element only — children still hydrate normally.
        <html lang="en" suppressHydrationWarning>
            <head>
                <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
            </head>
            <body className="bg-background text-foreground antialiased">
                <AppShell>{children}</AppShell>
            </body>
        </html>
    )
}
