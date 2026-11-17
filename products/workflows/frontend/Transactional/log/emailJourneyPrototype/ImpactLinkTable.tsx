// PROTOTYPE (ticket #385), throwaway. Each link in the email, compact enough to sit beside the funnel: who clicked,
// the sessions it started, who converted, and its most common problem.
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { ImpactData, ImpactLink, percent } from './impactFixtures'
import { LINK_TAG_DETAIL } from './ImpactFunnel'

export function ImpactLinkTable({ data }: { data: ImpactData }): JSX.Element {
    const maxClicked = Math.max(1, ...data.links.map((link) => link.clickedPeople))
    const topFinding = (link: ImpactLink): string | null =>
        data.scanner?.findings.find((finding) => finding.linkKey === link.key && finding.tone === 'problem')?.title ??
        null

    if (!data.links.length) {
        return (
            <p className="text-sm text-secondary m-0">
                Clicks aren't tracked for this email, so there's nothing per link.
            </p>
        )
    }

    return (
        <ul className="m-0 p-0 list-none flex flex-col divide-y" data-attr="prototype-impact-links">
            {data.links.map((link) => {
                const finding = topFinding(link)
                return (
                    <li key={link.key} className="py-2 flex flex-col gap-1">
                        <div className="flex items-center justify-between gap-2">
                            <div className="flex flex-col min-w-0">
                                <span className="font-semibold text-sm">{link.label}</span>
                                <span className="text-xs text-secondary truncate">
                                    {link.url.replace('https://', '')}
                                </span>
                            </div>
                            {link.tagged && link.sessions ? (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    to={urls.replay()}
                                    tooltip="Recordings of the sessions this link started"
                                >
                                    Recordings
                                </LemonButton>
                            ) : !link.tagged ? (
                                <Tooltip
                                    title={`This link leaves ${data.sendingDomain.replace(/^mail\./, '')}, so PostHog can't follow it.`}
                                >
                                    <LemonTag type="muted">Off your site</LemonTag>
                                </Tooltip>
                            ) : (
                                <Tooltip title={LINK_TAG_DETAIL}>
                                    <LemonTag type="muted">Needs link tagging</LemonTag>
                                </Tooltip>
                            )}
                        </div>
                        <div className="h-1.5 rounded bg-surface-secondary overflow-hidden">
                            <div
                                className="h-full bg-accent"
                                style={{ width: `${(link.clickedPeople / maxClicked) * 100}%` }}
                            />
                        </div>
                        <span className="text-xs">
                            {humanFriendlyNumber(link.clickedPeople)} clicked
                            {link.sessions !== null && ` · ${humanFriendlyNumber(link.sessions)} sessions`}
                            {link.converted !== null &&
                                data.goal &&
                                ` · ${humanFriendlyNumber(link.converted)} ${data.goal.event} (${percent(link.converted, link.clickedPeople)})`}
                        </span>
                        {finding && <span className="text-xs text-warning">{finding}</span>}
                    </li>
                )
            })}
        </ul>
    )
}
