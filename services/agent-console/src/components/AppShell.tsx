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

import { BotIcon, ExternalLinkIcon, LogOutIcon, MonitorIcon, MoonIcon, SunIcon, WalletIcon } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    ResizableHandle,
    ResizablePanel,
    ResizablePanelGroup,
    type Theme,
    ThemeProvider,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
    useTheme,
} from '@posthog/quill'

import { Dock } from './Dock'
import { DockContextProvider } from './dock-context'
import { FocusContextProvider } from './focus-context'
import { PostHogMark } from './PostHogMark'
import { SessionGate, SessionProvider, usePosthogBaseUrl, useSessionUser } from './session-context'
import { TopLoadingBar } from './TopLoadingBar'

export function AppShell({ children }: { children: React.ReactNode }): React.ReactElement {
    return (
        <ThemeProvider>
            <SessionProvider>
                <TooltipProvider delay={150}>
                    <DockContextProvider>
                        <FocusContextProvider>
                            <TopLoadingBar />
                            <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
                                <Sidebar />
                                <ResizablePanelGroup
                                    orientation="horizontal"
                                    defaultLayout={{ main: 70, dock: 30 }}
                                    className="flex-1"
                                >
                                    <ResizablePanel id="main" minSize="520px">
                                        <main className="h-full overflow-y-auto">
                                            <SessionGate>{children}</SessionGate>
                                        </main>
                                    </ResizablePanel>
                                    <ResizableHandle withHandle />
                                    <ResizablePanel id="dock" minSize="360px" maxSize="720px">
                                        <div className="h-full border-l border-border">
                                            <Dock />
                                        </div>
                                    </ResizablePanel>
                                </ResizablePanelGroup>
                            </div>
                        </FocusContextProvider>
                    </DockContextProvider>
                </TooltipProvider>
            </SessionProvider>
        </ThemeProvider>
    )
}

function Sidebar(): React.ReactElement {
    const pathname = usePathname() ?? '/'
    const isAgents = pathname === '/' || pathname.startsWith('/agents')
    const isBilling = pathname.startsWith('/billing')
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

            <SidebarTooltip label="Billing">
                <Link
                    href="/billing"
                    aria-label="Billing"
                    aria-current={isBilling ? 'page' : undefined}
                    className={
                        isBilling
                            ? 'inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md bg-accent text-foreground'
                            : 'inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground'
                    }
                >
                    <WalletIcon className="h-4 w-4" />
                </Link>
            </SidebarTooltip>

            {/* Bottom section: theme toggle + back to PostHog + user menu */}
            <div className="mt-auto flex flex-col items-center gap-2">
                <ThemeToggle />
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

function ThemeToggle(): React.ReactElement {
    const { theme, setTheme } = useTheme()
    // The trigger icon reflects the explicit preference (Monitor for
    // 'system') rather than the resolved value — Quill doesn't expose
    // the resolved theme through `useTheme`, and showing Monitor makes
    // it clear that the OS is in charge.
    const Icon = theme === 'dark' ? MoonIcon : theme === 'light' ? SunIcon : MonitorIcon
    return (
        <DropdownMenu>
            <SidebarTooltip label={`Theme: ${themeLabel(theme)}`}>
                <DropdownMenuTrigger
                    aria-label="Theme"
                    className="inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                    <Icon className="h-4 w-4" />
                </DropdownMenuTrigger>
            </SidebarTooltip>
            <DropdownMenuContent side="right" align="end">
                {/* `DropdownMenuLabel` is `MenuPrimitive.GroupLabel` under
                 *  the hood — Base UI throws "MenuGroupRootContext is
                 *  missing" unless it's inside a `DropdownMenuGroup`. */}
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Theme</DropdownMenuLabel>
                    <ThemeMenuItem
                        icon={<SunIcon className="h-3.5 w-3.5" />}
                        label="Light"
                        active={theme === 'light'}
                        onSelect={() => setTheme('light')}
                    />
                    <ThemeMenuItem
                        icon={<MoonIcon className="h-3.5 w-3.5" />}
                        label="Dark"
                        active={theme === 'dark'}
                        onSelect={() => setTheme('dark')}
                    />
                    <ThemeMenuItem
                        icon={<MonitorIcon className="h-3.5 w-3.5" />}
                        label="System"
                        active={theme === 'system'}
                        onSelect={() => setTheme('system')}
                    />
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function ThemeMenuItem({
    icon,
    label,
    active,
    onSelect,
}: {
    icon: React.ReactNode
    label: string
    active: boolean
    onSelect: () => void
}): React.ReactElement {
    return (
        <DropdownMenuItem onClick={onSelect} aria-checked={active} className="cursor-pointer">
            <span className="mr-2 inline-flex h-4 w-4 items-center justify-center text-muted-foreground">{icon}</span>
            <span className="flex-1">{label}</span>
            {active ? (
                <span aria-hidden className="text-[0.625rem] text-muted-foreground">
                    ●
                </span>
            ) : null}
        </DropdownMenuItem>
    )
}

function themeLabel(pref: Theme): string {
    return pref === 'system' ? 'System' : pref === 'dark' ? 'Dark' : 'Light'
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
                {/* `DropdownMenuLabel` is `MenuPrimitive.GroupLabel` so it
                 *  must live inside a `DropdownMenuGroup` to provide the
                 *  Base UI MenuGroupRootContext. */}
                <DropdownMenuGroup>
                    <DropdownMenuLabel>
                        <div className="flex flex-col">
                            <span className="text-sm font-medium">{user.displayName}</span>
                            {user.email ? <span className="text-xs text-muted-foreground">{user.email}</span> : null}
                        </div>
                    </DropdownMenuLabel>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                    <DropdownMenuItem
                        render={
                            // eslint-disable-next-line react/forbid-elements
                            <a href="/api/auth/logout" />
                        }
                    >
                        <LogOutIcon className="h-3.5 w-3.5" />
                        Sign out
                    </DropdownMenuItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
