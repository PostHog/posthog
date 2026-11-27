import { LemonBanner, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { EmailClickLinks, EmailClickRow, MAX_SHOWN_CLICKS, linkLabel } from './emailClicks'

export interface TransactionalEmailClicksProps {
    rows: EmailClickRow[]
    links: EmailClickLinks
    moreClicks: boolean
    onRetry: () => void
}

function ClickLink({ link, links }: { link: string | null; links: EmailClickLinks }): JSX.Element {
    if (link) {
        return (
            <Link to={link} target="_blank" className="text-sm truncate" title={link}>
                {linkLabel(link)}
            </Link>
        )
    }
    if (links === 'loading') {
        return <LemonSkeleton className="h-4 w-40" />
    }
    return <span className="text-sm text-secondary">Link not recorded</span>
}

export function TransactionalEmailClicks({
    rows,
    links,
    moreClicks,
    onRetry,
}: TransactionalEmailClicksProps): JSX.Element {
    return (
        <section
            className="ph-no-capture border rounded bg-surface-primary p-4 flex flex-col gap-3"
            data-attr="transactional-email-clicks"
        >
            <div className="flex flex-col gap-0.5">
                <h3 className="text-base font-semibold m-0">Clicks</h3>
                <p className="text-xs text-secondary m-0">Each click on the email's links, oldest first.</p>
            </div>
            {links === 'failed' && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: onRetry,
                        'data-attr': 'transactional-email-clicks-retry',
                    }}
                >
                    The links couldn't load. Check your connection and try again.
                </LemonBanner>
            )}
            {moreClicks && <p className="text-xs text-secondary m-0">Showing the newest {MAX_SHOWN_CLICKS} clicks.</p>}
            <ol className="list-none m-0 p-0 flex flex-col gap-2">
                {rows.map((row) => (
                    <li key={row.key} className="flex items-center gap-3 min-w-0">
                        <span className="w-24 shrink-0 text-xs text-secondary">
                            <TZLabel time={row.at} formatDate="MMM D" formatTime="HH:mm" />
                        </span>
                        <div className="flex-1 min-w-0 flex items-center gap-2">
                            <ClickLink link={row.link} links={links} />
                        </div>
                        <span className="shrink-0 text-xs text-secondary">No session yet</span>
                    </li>
                ))}
            </ol>
        </section>
    )
}
