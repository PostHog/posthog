/**
 * Storybook stub for `next/navigation`.
 *
 * Storybook runs under Vite, not Next.js, so `useRouter()` etc. would
 * otherwise throw. We `vite-alias` `next/navigation` to this module
 * (see `.storybook/main.ts`) so every story can render real components
 * that read from the router/path/search-params hooks.
 *
 * Story-local navigation is a no-op: `router.push()` logs to the
 * console, search params start empty, `usePathname()` returns `/`.
 * Add a Storybook decorator if a specific story needs to override.
 */

import * as React from 'react'

interface Router {
    push: (href: string) => void
    replace: (href: string) => void
    back: () => void
    forward: () => void
    refresh: () => void
    prefetch: () => void
}

const noopRouter: Router = {
    push: (href: string) => console.info('[story router] push →', href),
    replace: (href: string) => console.info('[story router] replace →', href),
    back: () => console.info('[story router] back'),
    forward: () => console.info('[story router] forward'),
    refresh: () => console.info('[story router] refresh'),
    prefetch: () => {},
}

export function useRouter(): Router {
    return noopRouter
}

export function usePathname(): string {
    return '/'
}

export function useSearchParams(): URLSearchParams {
    return React.useMemo(() => new URLSearchParams(), [])
}

export function useParams<T = Record<string, string>>(): T {
    return {} as T
}

export function notFound(): never {
    // eslint-disable-next-line no-console
    console.warn('[story router] notFound() called')
    throw new Error('notFound() called in storybook')
}

export function redirect(href: string): never {
    // eslint-disable-next-line no-console
    console.warn('[story router] redirect() →', href)
    throw new Error(`redirect("${href}") called in storybook`)
}

export const navigation = { useRouter, usePathname, useSearchParams, useParams, notFound, redirect }
