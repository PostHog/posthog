// PROTOTYPE (ticket #385), throwaway. The sent email, drawn in the app instead of the stored HTML iframe,
// so a variant can put something next to each link.
import type { ReactNode } from 'react'

import type { JourneyData, JourneyLink } from './journeyFixtures'

function DefaultLink({ link }: { link: JourneyLink }): JSX.Element {
    return <span className="text-[#2f80fa] underline">{link.label}</span>
}

export function JourneyEmailPreview({
    data,
    renderLink,
    compact = false,
}: {
    data: JourneyData
    renderLink?: (link: JourneyLink) => ReactNode
    compact?: boolean
}): JSX.Element {
    const link = (key: string): ReactNode => {
        const found = data.links.find((l) => l.key === key)!
        return renderLink ? renderLink(found) : <DefaultLink link={found} />
    }
    return (
        <section className="border rounded bg-surface-primary overflow-hidden">
            <dl className="m-0 px-4 py-3 border-b grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-secondary">To</dt>
                <dd className="m-0 truncate">{data.recipient}</dd>
                <dt className="text-secondary">Subject</dt>
                <dd className="m-0 font-semibold truncate">{data.subject}</dd>
            </dl>
            {/* Light like an email client, whatever the app theme. */}
            <div className={`bg-white text-[#151515] ${compact ? 'p-4 text-xs' : 'p-8 text-sm'}`}>
                <div className="max-w-[520px] mx-auto flex flex-col gap-3">
                    <div className="font-bold text-lg">Hedgebox</div>
                    <p className="m-0">Hi Mia,</p>
                    <p className="m-0">
                        Your trial ends in 3 days. Keep your 14 shared folders and everything in them by upgrading to a
                        paid plan.
                    </p>
                    <div className="py-2">{link('upgrade')}</div>
                    <p className="m-0">Not sure yet? Take another look at what you've stored: {link('files')}</p>
                    <p className="m-0">Questions about plans? Read the {link('faq')}.</p>
                    <p className="m-0 text-[#6b6b6b] text-xs">Hedgebox · Unsubscribe</p>
                </div>
            </div>
        </section>
    )
}
