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

export default function RootLayout({ children }: { children: React.ReactNode }): React.ReactElement {
    return (
        <html lang="en">
            <body className="bg-background text-foreground antialiased">
                <AppShell>{children}</AppShell>
            </body>
        </html>
    )
}
