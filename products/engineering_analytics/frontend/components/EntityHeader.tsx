// Shared entity header: icon square · title (+muted suffix) · mono slug line · verdict pill.

import { ReactNode } from 'react'

import { IconBox } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export type VerdictKind = 'success' | 'danger' | 'warning' | 'muted'

const PILL_CLASS: Record<VerdictKind, string> = {
    success: 'bg-fill-success-tertiary text-success',
    danger: 'bg-fill-error-tertiary text-danger',
    warning: 'bg-fill-warning-tertiary text-warning-dark',
    muted: 'bg-fill-secondary text-secondary',
}

const PILL_DOT: Record<VerdictKind, string> = {
    success: 'var(--success)',
    danger: 'var(--danger)',
    warning: 'var(--warning)',
    muted: 'var(--muted)',
}

/** One-glance verdict for the entity: "Failing on master · 38m", "CI passing", "3 open PRs". */
export function VerdictPill({ kind, children }: { kind: VerdictKind; children: ReactNode }): JSX.Element {
    return (
        <span
            className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold whitespace-nowrap',
                PILL_CLASS[kind]
            )}
        >
            <span
                className="inline-block size-2 shrink-0 rounded-full"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ backgroundColor: PILL_DOT[kind] }}
            />
            {children}
        </span>
    )
}

/** The repo's identity header, shared across the hub and secondary tabs so the subject reads the same
 *  everywhere: box icon · repo name · owner/name slug with a GitHub link. `right` docks the source
 *  picker on multi-source teams. */
export function RepoEntityHeader({ repoFullName, right }: { repoFullName: string; right?: ReactNode }): JSX.Element {
    const name = repoFullName.split('/')[1] || repoFullName || 'GitHub repository'
    return (
        <EntityHeader
            icon={<IconBox />}
            title={name}
            // No slug line when the source hasn't reported a repo name yet.
            slug={
                repoFullName ? (
                    <>
                        {repoFullName}
                        {' · '}
                        <Link to={`https://github.com/${repoFullName}`} target="_blank" targetBlankIcon>
                            View on GitHub
                        </Link>
                    </>
                ) : undefined
            }
            right={right}
        />
    )
}

export function EntityHeader({
    icon,
    title,
    titleSuffix,
    slug,
    right,
}: {
    icon?: ReactNode
    title: string
    /** Muted addition after the title (e.g. the run id). */
    titleSuffix?: ReactNode
    /** Mono context line under the title: repo/path, links, attempt, "View on GitHub". */
    slug: ReactNode
    right?: ReactNode
}): JSX.Element {
    return (
        <div className="flex items-start gap-3.5">
            {icon && (
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-primary bg-surface-primary text-lg">
                    {icon}
                </span>
            )}
            <div className="min-w-0">
                <h1 className="m-0 text-xl font-bold leading-tight tracking-tight">
                    {title}
                    {titleSuffix && <span className="ml-2 font-normal text-tertiary">{titleSuffix}</span>}
                </h1>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[11.5px] text-tertiary">
                    {slug}
                </div>
            </div>
            {right && <div className="ml-auto flex shrink-0 items-center gap-2">{right}</div>}
        </div>
    )
}
