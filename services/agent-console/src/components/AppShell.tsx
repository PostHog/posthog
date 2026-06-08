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

import {
    BotIcon,
    CheckSquareIcon,
    ExternalLinkIcon,
    LibraryIcon,
    Loader2Icon,
    LogOutIcon,
    MonitorIcon,
    MoonIcon,
    SunIcon,
    WalletIcon,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useCallback, useState } from 'react'
import { createPortal } from 'react-dom'

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

import { DOCK_TOGGLE_KEY_HINT, DOCK_TOGGLE_KEY_HINT_PC, DockLayoutProvider, useDockLayout } from '@/lib/useDockLayout'

import { Dock } from './Dock'
import { DockContextProvider, useDockStore } from './dock-context'
import { DockShowAffordance } from './DockShowAffordance'
import { FloatingDockPanel } from './FloatingDockPanel'
import { FocusContextProvider, useFocusStore } from './focus-context'
import { PostHogMark } from './PostHogMark'
import {
    SessionGate,
    SessionProvider,
    UnauthedScreen,
    usePosthogBaseUrl,
    useSession,
    useSessionUser,
} from './session-context'
import { TopLoadingBar } from './TopLoadingBar'

export function AppShell({ children }: { children: React.ReactNode }): React.ReactElement {
    return (
        <ThemeProvider>
            <SessionProvider>
                <TooltipProvider delay={150}>
                    <TopLoadingBar />
                    <AuthRoutedShell>{children}</AuthRoutedShell>
                </TooltipProvider>
            </SessionProvider>
        </ThemeProvider>
    )
}

/**
 * Forks the shell on auth state. The dock, sidebar nav, and main content
 * only make sense for an authenticated session — when the visitor has no
 * session we render a single centered "Sign in with PostHog" surface and
 * skip mounting the dock entirely (it would otherwise immediately try to
 * fetch agents and 401).
 *
 * While `/api/auth/me` is in flight (`loading: true`) we render a
 * neutral placeholder — NEITHER the authed chrome nor the unauthed
 * surface. Picking either eagerly causes a visible flash the moment
 * the fetch resolves the other way; a blank background is the least
 * jarring intermediate state.
 */
function AuthRoutedShell({ children }: { children: React.ReactNode }): React.ReactElement {
    const { loading, info } = useSession()

    if (loading) {
        return (
            <div
                className="flex h-screen w-screen items-center justify-center bg-background text-muted-foreground"
                aria-busy
                aria-live="polite"
            >
                <Loader2Icon className="h-5 w-5 animate-spin" aria-hidden />
                <span className="sr-only">Loading…</span>
            </div>
        )
    }

    if (info != null && !info.authenticated) {
        return (
            <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
                <UnauthedScreen />
            </div>
        )
    }

    return (
        <DockContextProvider>
            <FocusContextProvider>
                <DockLayoutProvider>
                    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
                        <Sidebar />
                        <ShellBody>{children}</ShellBody>
                    </div>
                    <ConciergeFocusIndicator />
                </DockLayoutProvider>
            </FocusContextProvider>
        </DockContextProvider>
    )
}

/**
 * Thin info-coloured bar pinned to the top edge of the viewport, only
 * visible when focus mode is on AND there's an active concierge
 * session. Communicates "the UI is following the concierge right now"
 * without stealing chrome from the page underneath. Click to pause.
 */
function ConciergeFocusIndicator(): React.ReactElement | null {
    const { enabled, setEnabled } = useFocusStore()
    const { activeConciergeSessionId } = useDockStore()
    if (!enabled || !activeConciergeSessionId) {
        return null
    }
    return (
        <button
            type="button"
            onClick={() => setEnabled(false)}
            aria-label="Concierge is following you — click to pause focus mode"
            title="Concierge is following you. Click to pause focus mode."
            className="fixed inset-x-0 top-0 z-50 h-1 cursor-pointer bg-info transition-opacity hover:opacity-80"
        />
    )
}

/**
 * Picks one of two layouts based on the user's dock-mode preference:
 *  - `rail` (default) → resizable two-pane split with the dock pinned right.
 *  - `floating` → main content fills the shell; the dock renders as a
 *    `<FloatingDockPanel />` overlay on top, freely draggable.
 *
 * `<Dock />` is rendered ONCE inside the shell and portaled into the
 * active chrome's slot. That keeps its runner / session state alive
 * across mode-toggle and visibility-toggle — switching docked ↔
 * floating no longer drops the running chat. Main content lives at a
 * stable React-tree position too for the same reason.
 *
 * The Dock falls back to a hidden parking node when no slot is active
 * (i.e. while the dock is hidden) so it stays mounted between every
 * toggle.
 */
function ShellBody({ children }: { children: React.ReactNode }): React.ReactElement {
    const { layout, setFloating, setVisible, embedSlot } = useDockLayout()

    // Callback refs feed React state so a re-render fires when the
    // active dock slot mounts. Without state we'd portal into stale refs.
    const [railSlot, setRailSlot] = useState<HTMLDivElement | null>(null)
    const [floatingSlot, setFloatingSlot] = useState<HTMLDivElement | null>(null)
    const [parkingSlot, setParkingSlot] = useState<HTMLDivElement | null>(null)

    const railSlotRef = useCallback((node: HTMLDivElement | null) => setRailSlot(node), [])
    const floatingSlotRef = useCallback((node: HTMLDivElement | null) => setFloatingSlot(node), [])
    const parkingSlotRef = useCallback((node: HTMLDivElement | null) => setParkingSlot(node), [])

    // An embed slot (registered by the active page) wins over the rail /
    // floating chrome — used by the overview to put the chat front-and-
    // centre. Always pick a non-null target so React never sees the
    // `<Portal>` go away.
    const dockTarget = embedSlot
        ? embedSlot
        : layout.visible && layout.mode === 'rail'
          ? railSlot
          : layout.visible && layout.mode === 'floating'
            ? floatingSlot
            : parkingSlot

    const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
    const shortcutHint = isMac ? DOCK_TOGGLE_KEY_HINT : DOCK_TOGGLE_KEY_HINT_PC

    // When an embed slot is active the side / floating chrome should
    // not render at all — the chat lives on the page itself, so a
    // pinned side panel would just duplicate the surface.
    const railChromeVisible = !embedSlot && layout.mode === 'rail' && layout.visible
    const floatingChromeVisible = !embedSlot && layout.mode === 'floating' && layout.visible
    const showAffordanceVisible = !embedSlot && !layout.visible

    return (
        <>
            {/* Main + rail chrome. The rail slot only renders when the user
             *  is in rail mode AND the dock is visible AND no embed slot
             *  has taken over — otherwise the whole panel + handle
             *  collapse so main takes the full width. */}
            <ResizablePanelGroup orientation="horizontal" defaultLayout={{ main: 70, dock: 30 }} className="flex-1">
                <ResizablePanel id="main" minSize="520px">
                    <main className="h-full overflow-y-auto">
                        <SessionGate>{children}</SessionGate>
                    </main>
                </ResizablePanel>
                {railChromeVisible ? (
                    <>
                        <ResizableHandle withHandle />
                        <ResizablePanel id="dock" minSize="360px" maxSize="720px">
                            <div ref={railSlotRef} className="h-full border-l border-border" />
                        </ResizablePanel>
                    </>
                ) : null}
            </ResizablePanelGroup>

            {/* Floating chrome. Same idea — only renders when active so the
             *  rail layout isn't fighting a phantom overlay. */}
            {floatingChromeVisible ? (
                <FloatingDockPanel floating={layout.floating} setFloating={setFloating}>
                    <div ref={floatingSlotRef} className="h-full" />
                </FloatingDockPanel>
            ) : null}

            {/* Parking spot for the Dock when no visible slot is active.
             *  Off-screen, but kept in the DOM so React keeps the runner mounted. */}
            <div ref={parkingSlotRef} className="sr-only" aria-hidden />

            {/* Show-dock affordance — only when hidden AND no embed is
             *  hosting the dock. */}
            {showAffordanceVisible ? (
                <DockShowAffordance layout={layout} onShow={() => setVisible(true)} shortcutHint={shortcutHint} />
            ) : null}

            {/* The one and only `<Dock />` instance. createPortal teleports
             *  its DOM into the active slot without React unmounting it. */}
            {dockTarget && createPortal(<Dock />, dockTarget)}
        </>
    )
}

function Sidebar(): React.ReactElement {
    const pathname = usePathname() ?? '/'
    const isHome = pathname === '/'
    const isAgents = pathname.startsWith('/agents')
    const isApprovals = pathname.startsWith('/approvals')
    const isRegistry = pathname.startsWith('/registry')
    const isBilling = pathname.startsWith('/billing')
    const posthogBaseUrl = usePosthogBaseUrl()

    return (
        <nav
            className="flex h-full w-14 shrink-0 flex-col items-center gap-2 border-r border-border py-3"
            aria-label="Primary"
        >
            <SidebarTooltip label={isHome ? 'PostHog agent console' : 'Home'}>
                <Link
                    href="/"
                    aria-label="Home"
                    aria-current={isHome ? 'page' : undefined}
                    className={
                        isHome
                            ? 'inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md bg-accent text-foreground'
                            : 'inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground'
                    }
                >
                    <PostHogMark className="h-6 w-6" />
                </Link>
            </SidebarTooltip>

            <div className="my-1 h-px w-6 bg-border" aria-hidden />

            <SidebarTooltip label="Agents">
                <Link
                    href="/agents"
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

            <SidebarTooltip label="Approvals">
                <Link
                    href="/approvals"
                    aria-label="Approvals"
                    aria-current={isApprovals ? 'page' : undefined}
                    className={
                        isApprovals
                            ? 'inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md bg-accent text-foreground'
                            : 'inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground'
                    }
                >
                    <CheckSquareIcon className="h-4 w-4" />
                </Link>
            </SidebarTooltip>

            <SidebarTooltip label="Tools & skills">
                <Link
                    href="/registry"
                    aria-label="Tools & skills"
                    aria-current={isRegistry ? 'page' : undefined}
                    className={
                        isRegistry
                            ? 'inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md bg-accent text-foreground'
                            : 'inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground'
                    }
                >
                    <LibraryIcon className="h-4 w-4" />
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
