import { IconArrowRight, IconExternal, IconTarget } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import type { IdentityMatchingLinkApi, IdentityMatchingPersonApi } from './generated/api.schemas'
import {
    PERSON_CAMPAIGN_FIELDS,
    hasCampaign,
    linkPersonDisplay,
    normalizedScore,
    personField,
} from './identityMatchingUtils'

/** Compact one-line campaign descriptor for a person, e.g. "google · cpc · spring_sale" or a referrer. */
function campaignLabel(person: IdentityMatchingPersonApi | null | undefined): string | null {
    const parts = [
        personField(person, 'utm_source'),
        personField(person, 'utm_medium'),
        personField(person, 'utm_campaign'),
    ].filter((value): value is string => value !== null)
    if (parts.length > 0) {
        return parts.join(' · ')
    }
    return personField(person, 'referring_domain')
}

function CampaignAttribution({ link }: { link: IdentityMatchingLinkApi }): JSX.Element | null {
    if (!hasCampaign(link.orphan_person) && !hasCampaign(link.anchor_person)) {
        return null
    }
    const rows = PERSON_CAMPAIGN_FIELDS.map((field) => ({
        label: field.label,
        orphan: personField(link.orphan_person, field.key),
        anchor: personField(link.anchor_person, field.key),
    })).filter((row) => row.orphan !== null || row.anchor !== null)

    return (
        <div className="rounded-md bg-bg-light border border-border p-2 text-xs">
            <div className="grid grid-cols-[6rem_minmax(0,1fr)_minmax(0,1fr)] gap-x-3 font-semibold text-tertiary pb-1 mb-1 border-b border-border">
                <span>Campaign</span>
                <span>Visitor</span>
                <span>Person</span>
            </div>
            <div className="flex flex-col gap-0.5">
                {rows.map((row) => (
                    <div key={row.label} className="grid grid-cols-[6rem_minmax(0,1fr)_minmax(0,1fr)] gap-x-3">
                        <span className="text-tertiary">{row.label}</span>
                        <span className="truncate" title={row.orphan ?? undefined}>
                            {row.orphan ?? <span className="text-muted">—</span>}
                        </span>
                        <span className="truncate" title={row.anchor ?? undefined}>
                            {row.anchor ?? <span className="text-muted">—</span>}
                        </span>
                    </div>
                ))}
            </div>
        </div>
    )
}

interface TimelineStep {
    label: string
    description: string
    tone: 'completion' | 'highlight' | 'muted'
}

function buildTimeline(link: IdentityMatchingLinkApi): TimelineStep[] {
    const steps: TimelineStep[] = []

    if (link.orphan_paid_touch) {
        steps.push({
            label: 'Paid ad click',
            description: 'The anonymous visitor arrived via a paid ad click (e.g. Google Ads, LinkedIn, TikTok).',
            tone: 'completion',
        })
    }

    steps.push({
        label: 'Shared network',
        description: `Both identities were seen on the same IP address on ${link.shared_ip_days} day${link.shared_ip_days === 1 ? '' : 's'}, suggesting the same person on the same network.`,
        tone: 'highlight',
    })

    if (link.ua_exact_match) {
        steps.push({
            label: 'Same device',
            description:
                'An identical browser user agent was seen on both identities — likely the same physical device.',
            tone: 'highlight',
        })
    }

    if (link.avg_path_jaccard > 0) {
        steps.push({
            label: 'Browsed same pages',
            description: `${Math.round(link.avg_path_jaccard * 100)}% overlap in pages visited on shared IP days.`,
            tone: 'muted',
        })
    }

    steps.push({
        label: 'Identified person',
        description: link.anchor_paid_touch
            ? 'The visitor was already identified — both the ad click and the identification belong to the same person.'
            : 'The visitor later identified themselves (e.g. signed up). This match links the earlier anonymous ad click to them.',
        tone: 'completion',
    })

    return steps
}

const DOT_CLASS: Record<TimelineStep['tone'], string> = {
    completion: 'bg-success border-success',
    highlight: 'bg-accent border-accent',
    muted: 'bg-surface-secondary border-border',
}

function PaidTimelineCard({ link }: { link: IdentityMatchingLinkApi }): JSX.Element {
    const steps = buildTimeline(link)
    const confidence = normalizedScore(link)
    const pct = Math.round(confidence * 100)

    return (
        <div className="rounded-lg border border-primary bg-surface-secondary p-4 space-y-3">
            {/* Identity pair */}
            <div className="flex items-center gap-3">
                <div className="flex-1 min-w-0">
                    <div className="text-xs text-tertiary mb-0.5">Anonymous visitor</div>
                    <PersonDisplay
                        person={linkPersonDisplay(link.orphan_person, link.orphan_distinct_id)}
                        noPopover
                        withIcon="sm"
                    />
                </div>
                <IconArrowRight className="text-lg text-tertiary shrink-0" />
                <div className="flex-1 min-w-0">
                    <div className="text-xs text-tertiary mb-0.5">Identified person</div>
                    <PersonDisplay
                        person={linkPersonDisplay(link.anchor_person, link.anchor_person_key)}
                        noPopover
                        withIcon="sm"
                    />
                </div>
                <div className="shrink-0 text-right">
                    <LemonTag type={pct >= 70 ? 'success' : pct >= 40 ? 'warning' : 'default'}>{pct}%</LemonTag>
                    <div className="text-xs text-tertiary mt-1">{link.model_version}</div>
                </div>
            </div>

            {/* Timeline */}
            <div className="pl-1">
                <div className="relative">
                    {/* Vertical line — sits behind the dots, centered on them */}
                    <div className="absolute left-[7px] top-3 bottom-3 w-px bg-border" />
                    <div className="space-y-3">
                        {steps.map((step, i) => (
                            <div key={i} className="flex items-start gap-3">
                                <div
                                    className={`size-3.5 rounded-full border-2 shrink-0 mt-0.5 ${DOT_CLASS[step.tone]}`}
                                />
                                <div className="min-w-0 flex-1">
                                    <div className="text-sm font-medium">{step.label}</div>
                                    <p className="text-xs text-tertiary">{step.description}</p>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* Campaign attribution — the recovered paid touch, plus the identified person's own campaign */}
            <CampaignAttribution link={link} />

            {/* Footer */}
            <div className="flex items-center justify-between pt-2 border-t border-border">
                <span className="text-xs text-tertiary">
                    Computed {dayjs(link.computed_at).format('MMM D, YYYY HH:mm')}
                </span>
                <div className="flex gap-1">
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconExternal />}
                        to={urls.personByDistinctId(link.orphan_distinct_id)}
                    >
                        Visitor
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconExternal />}
                        to={urls.personByDistinctId(link.anchor_person_key)}
                    >
                        Person
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

function PaidAttributionTable({ links }: { links: IdentityMatchingLinkApi[] }): JSX.Element {
    const columns: LemonTableColumns<IdentityMatchingLinkApi> = [
        {
            title: 'Anonymous visitor',
            dataIndex: 'orphan_distinct_id',
            render: (_, link) => (
                <PersonDisplay
                    person={linkPersonDisplay(link.orphan_person, link.orphan_distinct_id)}
                    noPopover
                    withIcon="sm"
                />
            ),
        },
        {
            title: 'Visitor campaign',
            key: 'orphan_campaign',
            render: (_, link) => {
                const label = campaignLabel(link.orphan_person)
                return label ? <span className="text-xs">{label}</span> : <span className="text-muted">—</span>
            },
        },
        {
            title: 'Identified person',
            dataIndex: 'anchor_person_key',
            render: (_, link) => (
                <PersonDisplay
                    person={linkPersonDisplay(link.anchor_person, link.anchor_person_key)}
                    noPopover
                    withIcon="sm"
                />
            ),
        },
        {
            title: 'Person campaign',
            key: 'anchor_campaign',
            render: (_, link) => {
                const label = campaignLabel(link.anchor_person)
                return label ? <span className="text-xs">{label}</span> : <span className="text-muted">—</span>
            },
        },
        {
            title: 'Confidence',
            key: 'confidence',
            render: (_, link) => {
                const pct = Math.round(normalizedScore(link) * 100)
                return <LemonTag type={pct >= 70 ? 'success' : pct >= 40 ? 'warning' : 'default'}>{pct}%</LemonTag>
            },
            width: 100,
        },
        {
            title: 'IP days',
            dataIndex: 'shared_ip_days',
            width: 80,
            render: (_, link) => <span className="font-mono tabular-nums">{link.shared_ip_days}</span>,
        },
        {
            title: 'Same UA',
            dataIndex: 'ua_exact_match',
            width: 80,
            render: (_, link) => (link.ua_exact_match ? <LemonTag type="highlight">Yes</LemonTag> : '—'),
        },
        {
            title: 'Type',
            key: 'type',
            width: 110,
            render: (_, link) =>
                link.anchor_paid_touch ? (
                    <LemonTag type="highlight">Confirmed</LemonTag>
                ) : (
                    <LemonTag type="completion">Recovered</LemonTag>
                ),
        },
        {
            title: 'Computed',
            dataIndex: 'computed_at',
            width: 140,
            render: (_, link) => dayjs(link.computed_at).format('MMM D, HH:mm'),
        },
    ]

    return (
        <LemonTable
            dataSource={links}
            columns={columns}
            rowKey={(link) => `${link.model_version}:${link.orphan_distinct_id}`}
            pagination={{ pageSize: 50 }}
            size="small"
            nouns={['attribution', 'attributions']}
        />
    )
}

export function PaidAttributionTimeline({ links }: { links: IdentityMatchingLinkApi[] }): JSX.Element {
    const paidLinks = links.filter((l) => l.orphan_paid_touch && !l.anchor_paid_touch)
    const continuityLinks = links.filter((l) => l.orphan_paid_touch && l.anchor_paid_touch)
    const allPaid = [...paidLinks, ...continuityLinks]

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <IconTarget className="text-lg" />
                <h3 className="text-base font-semibold">Paid attribution</h3>
                <Tooltip title="Links where an anonymous visitor arrived via a paid ad click, and the match recovers attribution to the identified person. 'Recovered' means the ad click was on the anonymous identity; 'Confirmed' means both sides had the paid click.">
                    <span className="text-xs text-tertiary underline decoration-dotted cursor-help">
                        How this works
                    </span>
                </Tooltip>
            </div>
            {allPaid.length === 0 ? (
                <p className="text-sm text-tertiary">
                    No paid ad touches found in the current results. When the identity matching job links an anonymous
                    visitor who clicked a paid ad to an identified person, they will appear here as a recovered
                    attribution timeline.
                </p>
            ) : (
                <>
                    {/* Summary stats */}
                    <div className="flex items-center gap-3 text-sm">
                        <span className="text-secondary">
                            <LemonTag type="completion">{paidLinks.length}</LemonTag> recovered
                        </span>
                        <span className="text-secondary">
                            <LemonTag type="highlight">{continuityLinks.length}</LemonTag> confirmed
                        </span>
                        <span className="text-tertiary">· {allPaid.length} total</span>
                    </div>

                    {/* Compact table view when there are many attributions, card timeline when few */}
                    {allPaid.length > 20 ? (
                        <PaidAttributionTable links={allPaid} />
                    ) : (
                        <>
                            {paidLinks.length > 0 && (
                                <div className="space-y-3">
                                    <div className="flex items-center gap-2">
                                        <span className="text-sm font-medium">Recovered</span>
                                        <span className="text-xs text-tertiary">
                                            Ad clicks on anonymous visitors, now linked to known users
                                        </span>
                                    </div>
                                    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                                        {paidLinks.map((link) => (
                                            <PaidTimelineCard
                                                key={`${link.model_version}:${link.orphan_distinct_id}`}
                                                link={link}
                                            />
                                        ))}
                                    </div>
                                </div>
                            )}
                            {continuityLinks.length > 0 && (
                                <div className="space-y-3">
                                    <div className="flex items-center gap-2">
                                        <span className="text-sm font-medium">Confirmed</span>
                                        <span className="text-xs text-tertiary">
                                            Both identities had paid ad clicks — match confirms same person across the
                                            journey
                                        </span>
                                    </div>
                                    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                                        {continuityLinks.map((link) => (
                                            <PaidTimelineCard
                                                key={`${link.model_version}:${link.orphan_distinct_id}`}
                                                link={link}
                                            />
                                        ))}
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </>
            )}
        </div>
    )
}
