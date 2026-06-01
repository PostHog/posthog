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
 * Renders a plain `<a>` and forwards through `href` + arbitrary
 * anchor props. Next-specific props (`prefetch`, `replace`, `scroll`,
 * `shallow`, `passHref`, `legacyBehavior`, `as`) are accepted and
 * ignored — the goal is module-init parity, not feature parity.
 */

import * as React from 'react'

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
        children,
        ...rest
    },
    ref
) {
    const resolved = typeof href === 'string' ? href : (href.pathname ?? '#')
    return (
        // eslint-disable-next-line react/forbid-elements
        <a ref={ref} href={resolved} {...rest}>
            {children}
        </a>
    )
})

export default Link
