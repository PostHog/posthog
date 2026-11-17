// PROTOTYPE (ticket #385), throwaway. List option L3: a strip of highlights across all emails sits above a table close
// to today's. Each highlight names an email and leads to its impact page, or fixes a gap in one click.
import { type ReactNode, useState } from 'react'

import { IconSparkles, IconTrending, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { SCANNER_SUGGESTIONS } from './ImpactFindings'
import { percent } from './impactFixtures'
import { ConversionCell, EmailName, impactUrl, ReplayVisionCell, Sparkline } from './ListCells'
import { conversionRate, ListEmail } from './listFixtures'
import { useEmailJourneyPrototype } from './useEmailJourneyPrototype'

function Highlight({ icon, title, children }: { icon: JSX.Element; title: string; children: ReactNode }): JSX.Element {
    return (
        <section className="flex-1 min-w-64 border rounded bg-surface-primary p-3 flex flex-col gap-1">
            <span className="flex items-center gap-1 text-xs text-secondary font-semibold uppercase tracking-wide">
                {icon}
                {title}
            </span>
            {children}
        </section>
    )
}

export function VariantListHighlights({ emails }: { emails: ListEmail[] }): JSX.Element {
    const { journeyCase } = useEmailJourneyPrototype()
    const [watchingAll, setWatchingAll] = useState(false)
    const ranked = emails
        .filter((email) => conversionRate(email) !== null && email.clicked !== null)
        .sort((a, b) => conversionRate(b)! - conversionRate(a)!)
    const best = ranked[0]
    const worst = ranked[ranked.length - 1]
    const problem = emails.find((email) => email.scanner?.topProblem)
    const unwatched = emails.filter((email) => !email.scanner && email.clicked !== null)
    const noGoal = emails.filter((email) => !email.goal && email.clicked !== null)
    const canWatch = journeyCase === 'full'

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-3" data-attr="prototype-list-highlights">
                {best && (
                    <Highlight icon={<IconTrending />} title="Converts best">
                        <Link to={impactUrl(best)} className="font-semibold">
                            {best.name}
                        </Link>
                        <span className="text-sm">
                            {percent(best.converted!, best.clicked!)} of people who clicked did "{best.goal}"
                        </span>
                    </Highlight>
                )}
                {worst && worst !== best && (
                    <Highlight icon={<IconWarning className="text-warning" />} title="Loses people after the click">
                        <Link to={impactUrl(worst)} className="font-semibold">
                            {worst.name}
                        </Link>
                        <span className="text-sm">
                            {humanFriendlyNumber(worst.clicked!)} clicked, {percent(worst.converted!, worst.clicked!)}{' '}
                            did "{worst.goal}"
                        </span>
                    </Highlight>
                )}
                {problem?.scanner && (
                    <Highlight icon={<IconSparkles />} title="Replay vision found">
                        <Link to={impactUrl(problem)} className="font-semibold">
                            {problem.scanner.topProblem}
                        </Link>
                        <span className="text-sm">
                            In sessions from {problem.name}, plus {problem.scanner.problems - 1} more problems
                        </span>
                    </Highlight>
                )}
                {unwatched.length > 0 && (
                    <Highlight icon={<IconSparkles />} title="Not watched yet">
                        <span className="text-sm">
                            Replay vision doesn't watch the sessions from {unwatched.length} emails.
                        </span>
                        {!canWatch ? (
                            <span className="text-xs text-secondary">
                                {journeyCase === 'no-landing'
                                    ? 'Needs link tagging first.'
                                    : 'Needs session replay first.'}
                            </span>
                        ) : watchingAll ? (
                            <LemonTag type="highlight" icon={<IconSparkles />} className="self-start">
                                Watching sessions from all emails
                            </LemonTag>
                        ) : (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                className="self-start"
                                onClick={() => setWatchingAll(true)}
                                tooltip={`One scanner per email: "${SCANNER_SUGGESTIONS[0].question}"`}
                                data-attr="prototype-list-watch-all"
                            >
                                Watch all
                            </LemonButton>
                        )}
                    </Highlight>
                )}
                {noGoal.length > 0 && (
                    <Highlight icon={<IconWarning />} title="No conversion event">
                        <span className="text-sm">
                            {noGoal.map((email) => email.name).join(', ')} {noGoal.length === 1 ? 'has' : 'have'} no
                            event that counts as converted.
                        </span>
                        <Link to={impactUrl(noGoal[0], 'no-goal')} className="text-sm">
                            Pick one
                        </Link>
                    </Highlight>
                )}
            </div>
            <LemonTable<ListEmail>
                dataSource={emails}
                rowKey="id"
                columns={[
                    { title: 'Name', key: 'name', render: (_, email) => <EmailName email={email} /> },
                    {
                        title: 'Last 30 days',
                        key: 'sent',
                        render: (_, email) => (
                            <div className="flex items-center gap-2 text-secondary">
                                <Sparkline values={email.daily} />
                                <span className="text-primary">{humanFriendlyNumber(email.sent)} sent</span>
                            </div>
                        ),
                    },
                    { title: 'Converted', key: 'converted', render: (_, email) => <ConversionCell email={email} /> },
                    {
                        title: 'Replay vision',
                        key: 'vision',
                        render: (_, email) =>
                            watchingAll && !email.scanner && email.clicked !== null ? (
                                <LemonTag type="highlight" icon={<IconSparkles />}>
                                    Watching sessions
                                </LemonTag>
                            ) : (
                                <ReplayVisionCell email={email} />
                            ),
                    },
                ]}
            />
        </div>
    )
}
