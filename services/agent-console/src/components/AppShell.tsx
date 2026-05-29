/**
 * Three-column app shell:
 *  - Thin left rail with the nav (PostHog logo, top-level surfaces,
 *    back-to-PostHog escape hatch, user menu at the bottom)
 *  - Main content (the active route)
 *  - Right dock (ambient `<AgentChat />`)
 *
 * The dock is fixed-width, full-height, always present. The left rail
 * is narrow on purpose — the agent platform doesn't have many
 * top-level surfaces. Each rail item has a tooltip that names it.
 */

'use client'

import { BotIcon, ExternalLinkIcon, LogOutIcon } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@posthog/quill'

import { Dock } from './Dock'
import { DockContextProvider } from './dock-context'
import { FocusContextProvider } from './focus-context'
import { PostHogMark } from './PostHogMark'
import { SessionGate, SessionProvider, usePosthogBaseUrl, useSessionUser } from './session-context'

const DOCK_WIDTH = 360

export function AppShell({ children }: { children: React.ReactNode }): React.ReactElement {
    return (
        <SessionProvider>
            <TooltipProvider delay={150}>
                <DockContextProvider>
                    <FocusContextProvider>
                        <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
                            <Sidebar />
                            <main className="flex-1 overflow-y-auto">
                                <SessionGate>{children}</SessionGate>
                            </main>
                            <aside className="shrink-0 border-l border-border" style={{ width: DOCK_WIDTH }}>
                                <Dock />
                            </aside>
                        </div>
                    </FocusContextProvider>
                </DockContextProvider>
            </TooltipProvider>
        </SessionProvider>
    )
}

function Sidebar(): React.ReactElement {
    const pathname = usePathname() ?? '/'
    const isAgents = pathname === '/' || pathname.startsWith('/agents')
    const posthogBaseUrl = usePosthogBaseUrl()

    return (
        <nav
            className="flex h-full w-14 shrink-0 flex-col items-center gap-2 border-r border-border py-3"
            aria-label="Primary"
        >
            <SidebarTooltip label="PostHog agent console">
                <Link
                    href="/"
                    aria-label="PostHog agent console"
                    className="inline-flex h-9 w-9 cursor-pointer items-center justify-center"
                >
                    <PostHogMark className="h-6 w-6" />
                </Link>
            </SidebarTooltip>

            <div className="my-1 h-px w-6 bg-border" aria-hidden />

            <SidebarTooltip label="Agents">
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
            </SidebarTooltip>

            {/* Bottom section: back to PostHog + user menu */}
            <div className="mt-auto flex flex-col items-center gap-2">
                {posthogBaseUrl ? (
                    <SidebarTooltip label="Back to PostHog">
                        {/* eslint-disable-next-line react/forbid-elements */}
                        <a
                            href={posthogBaseUrl}
                            aria-label="Back to PostHog"
                            className="inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                        >
                            <ExternalLinkIcon className="h-4 w-4" />
                        </a>
                    </SidebarTooltip>
                ) : null}
                <UserMenu />
            </div>
        </nav>
    )
}

function SidebarTooltip({ label, children }: { label: string; children: React.ReactNode }): React.ReactElement {
    return (
        <Tooltip>
            <TooltipTrigger render={<div />}>{children}</TooltipTrigger>
            <TooltipContent side="right">{label}</TooltipContent>
        </Tooltip>
    )
}

function UserMenu(): React.ReactElement | null {
    const user = useSessionUser()
    if (!user) {
        return null
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                aria-label={`Signed in as ${user.displayName}`}
                className="inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-full bg-muted text-[0.6875rem] font-medium uppercase tracking-wide text-foreground transition-colors hover:bg-accent"
            >
                {user.initials}
            </DropdownMenuTrigger>
            <DropdownMenuContent side="right" align="end">
                <DropdownMenuLabel>
                    <div className="flex flex-col">
                        <span className="text-sm font-medium">{user.displayName}</span>
                        {user.email ? <span className="text-xs text-muted-foreground">{user.email}</span> : null}
                    </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    render={
                        // eslint-disable-next-line react/forbid-elements
                        <a href="/api/auth/logout" />
                    }
                >
                    <LogOutIcon className="h-3.5 w-3.5" />
                    Sign out
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
