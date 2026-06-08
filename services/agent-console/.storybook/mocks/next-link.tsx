/**
 * Storybook stub for `next/link`.
 *
 * Storybook runs under Vite, not Next.js. The real `next/link` reads
 * `process.env.*` at module init (for `__NEXT_TRUSTED_ORIGINS` etc.)
 * which crashes in a browser context with `ReferenceError: process is
 * not defined`. We `vite-alias` `next/link` to this module (see
 * `.storybook/main.ts`) so stories can render shells that use `<Link>`
 * without the runtime even loading the real Next module.
 *
 * Renders a plain `<a>` whose `onClick` calls `navigate()` on the
 * shared router store — so clicking a link inside the navigable
 * AppShell story drives a soft route change rather than a browser
 * navigation. Modifier-clicks (cmd/ctrl/shift/alt + click) fall
 * through to the default browser behaviour, matching real `next/link`.
 */

import * as React from 'react'

import { navigate } from './router-store'

interface NextLinkProps extends Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
    href: string | { pathname?: string; query?: Record<string, string | number | string[]> }
    prefetch?: boolean
    replace?: boolean
    scroll?: boolean
    shallow?: boolean
    passHref?: boolean
    legacyBehavior?: boolean
    as?: string
}

function hrefToString(href: NextLinkProps['href']): string {
    return typeof href === 'string' ? href : (href.pathname ?? '#')
}

const Link = React.forwardRef<HTMLAnchorElement, NextLinkProps>(function Link(
    {
        href,
        prefetch: _prefetch,
        replace: _replace,
        scroll: _scroll,
        shallow: _shallow,
        passHref: _passHref,
        legacyBehavior: _legacyBehavior,
        as: _as,
        onClick,
        children,
        ...rest
    },
    ref
) {
    const resolved = hrefToString(href)
    const handleClick = (e: React.MouseEvent<HTMLAnchorElement>): void => {
        onClick?.(e)
        if (e.defaultPrevented) {
            return
        }
        // Let modifier-clicks open in new tab / window etc.
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) {
            return
        }
        // External / absolute hrefs: leave as real navigation.
        if (/^[a-z]+:\/\//i.test(resolved) || resolved.startsWith('mailto:') || resolved.startsWith('tel:')) {
            return
        }
        e.preventDefault()
        navigate(resolved)
    }
    return (
        // eslint-disable-next-line react/forbid-elements
        <a ref={ref} href={resolved} onClick={handleClick} {...rest}>
            {children}
        </a>
    )
})

export default Link
