/**
 * Three-column app shell:
 *  - Thin left rail with the nav (minimal — agents + a placeholder
 *    for future top-level surfaces)
 *  - Main content (the active route)
 *  - Right dock (ambient `<AgentChat />`)
 *
 * The dock is fixed-width, full-height, always present. The left rail
 * is narrow on purpose — the agent platform doesn't have many
 * top-level surfaces.
 */

'use client'

import { BotIcon } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { Dock } from './Dock'
import { DockContextProvider } from './dock-context'
import { FocusContextProvider } from './focus-context'
import { PostHogMark } from './PostHogMark'

const DOCK_WIDTH = 360

export function AppShell({ children }: { children: React.ReactNode }): React.ReactElement {
    return (
        <DockContextProvider>
            <FocusContextProvider>
                <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
                    <Sidebar />
                    <main className="flex-1 overflow-y-auto">{children}</main>
                    <aside className="shrink-0 border-l border-border" style={{ width: DOCK_WIDTH }}>
                        <Dock />
                    </aside>
                </div>
            </FocusContextProvider>
        </DockContextProvider>
    )
}

function Sidebar(): React.ReactElement {
    const pathname = usePathname() ?? '/'
    const isAgents = pathname === '/' || pathname.startsWith('/agents')

    return (
        <nav
            className="flex h-full w-14 shrink-0 flex-col items-center gap-2 border-r border-border py-3"
            aria-label="Primary"
        >
            <Link
                href="/"
                aria-label="PostHog agent console"
                className="inline-flex h-9 w-9 cursor-pointer items-center justify-center"
                title="PostHog agent console"
            >
                <PostHogMark className="h-6 w-6" />
            </Link>
            <div className="my-1 h-px w-6 bg-border" aria-hidden />
            <Link
                href="/"
                aria-label="Agents"
                aria-current={isAgents ? 'page' : undefined}
                className={
                    isAgents
                        ? 'inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md bg-accent text-foreground'
                        : 'inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground'
                }
            >
                <BotIcon className="h-4 w-4" />
            </Link>
        </nav>
    )
}
