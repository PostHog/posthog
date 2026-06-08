/**
 * Storybook stub for `next/navigation`.
 *
 * Storybook runs under Vite, not Next.js, so `useRouter()` etc. would
 * otherwise throw. We `vite-alias` `next/navigation` to this module
 * (see `.storybook/main.ts`) so every story can render real components
 * that read from the router/path/search-params hooks.
 *
 * Navigation is backed by `./router-store` — a small in-memory pub-sub
 * shared with the `<Link>` mock and the `<StoryRoutes>` switch the
 * shell story uses. `router.push(href)` updates the store, every
 * subscriber re-renders, the switch resolves the new path to a page.
 */

import * as React from 'react'

import { getSnapshot, navigate, subscribe } from './router-store'

interface Router {
    push: (href: string) => void
    replace: (href: string) => void
    back: () => void
    forward: () => void
    refresh: () => void
    prefetch: () => void
}

const router: Router = {
    push: (href: string) => navigate(href),
    replace: (href: string) => navigate(href),
    back: () => console.info('[story router] back'),
    forward: () => console.info('[story router] forward'),
    refresh: () => console.info('[story router] refresh'),
    prefetch: () => {},
}

export function useRouter(): Router {
    return router
}

function usePathFull(): string {
    return React.useSyncExternalStore(
        subscribe,
        () => getSnapshot().path,
        () => '/'
    )
}

function useParamsRecord(): Record<string, string> {
    return React.useSyncExternalStore(
        subscribe,
        () => getSnapshot().params,
        () => ({})
    )
}

export function usePathname(): string {
    const full = usePathFull()
    const qIdx = full.indexOf('?')
    return qIdx === -1 ? full : full.slice(0, qIdx)
}

export function useSearchParams(): URLSearchParams {
    const full = usePathFull()
    const qIdx = full.indexOf('?')
    const qs = qIdx === -1 ? '' : full.slice(qIdx + 1)
    return React.useMemo(() => new URLSearchParams(qs), [qs])
}

export function useParams<T = Record<string, string>>(): T {
    return useParamsRecord() as T
}

export function notFound(): never {
    console.warn('[story router] notFound() called')
    throw new Error('notFound() called in storybook')
}

export function redirect(href: string): never {
    console.warn('[story router] redirect() →', href)
    navigate(href)
    throw new Error(`redirect("${href}") called in storybook`)
}

export const navigation = { useRouter, usePathname, useSearchParams, useParams, notFound, redirect }
