import { IconArrowRight, IconCheck, IconExternal } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import type { IdentityMatchingLinkApi } from './generated/api.schemas'
import {
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    PERSON_CAMPAIGN_FIELDS,
    PERSON_SIGNAL_FIELDS,
    type PersonFieldSpec,
    type SignalCategory,
    extractEmail,
    extractSignals,
    linkPersonDisplay,
    normalizedScore,
    personField,
} from './identityMatchingUtils'

const CATEGORY_TAG_TYPE: Record<SignalCategory, 'default' | 'highlight' | 'completion'> = {
    network: 'highlight',
    device: 'highlight',
    behavior: 'default',
    attribution: 'completion',
}

const STRENGTH_LABELS: Record<number, string> = {
    1: 'Weak signal',
    2: 'Moderate signal',
    3: 'Strong signal',
}

// Shared 3-column grid so the header and every comparison row line up: label · visitor · person.
const COMPARE_GRID = 'grid grid-cols-[7rem_minmax(0,1fr)_minmax(0,1fr)] gap-x-3'

function matchSummary(link: IdentityMatchingLinkApi, confidence: number): string {
    const signals = extractSignals(link)
    const topSignals = signals.filter((s) => s.strength >= 2).slice(0, 2)
    const reasons = topSignals.map((s) => s.label.toLowerCase()).join(' and ')
    const pct = Math.round(confidence * 100)
    const personLabel = link.anchor_person?.email ?? extractEmail(link.anchor_person_key) ?? 'this identified person'
    if (reasons) {
        return `We're ${pct}% confident this anonymous visitor is ${personLabel}, because they ${reasons}.`
    }
    return `We're ${pct}% confident this anonymous visitor is ${personLabel}.`
}

function CompareSection({
    title,
    fields,
    link,
}: {
    title: string
    fields: PersonFieldSpec[]
    link: IdentityMatchingLinkApi
}): JSX.Element | null {
    const rows = fields
        .map((field) => ({
            label: field.label,
            orphan: personField(link.orphan_person, field.key),
            anchor: personField(link.anchor_person, field.key),
        }))
        .filter((row) => row.orphan !== null || row.anchor !== null)

    if (rows.length === 0) {
        return null
    }

    return (
        <div>
            <div className="text-xs font-semibold text-tertiary mb-1">{title}</div>
            <div className="flex flex-col">
                {rows.map((row) => {
                    const isMatch =
                        row.orphan !== null &&
                        row.anchor !== null &&
                        row.orphan.toLowerCase() === row.anchor.toLowerCase()
                    return (
                        <div
                            key={row.label}
                            className={`${COMPARE_GRID} items-center py-1 border-b border-border last:border-0`}
                        >
                            <span className="text-xs text-tertiary">{row.label}</span>
                            <span className="text-sm truncate" title={row.orphan ?? undefined}>
                                {row.orphan ?? <span className="text-muted">—</span>}
                            </span>
                            <span
                                className={`text-sm flex items-center gap-1 ${isMatch ? 'text-success font-medium' : ''}`}
                            >
                                <span className="truncate" title={row.anchor ?? undefined}>
                                    {row.anchor ?? <span className="text-muted">—</span>}
                                </span>
                                {isMatch && (
                                    <Tooltip title="Same value on both sides">
                                        <IconCheck className="shrink-0" />
                                    </Tooltip>
                                )}
                            </span>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

function PersonCard({
    label,
    link,
    side,
}: {
    label: string
    link: IdentityMatchingLinkApi
    side: 'orphan' | 'anchor'
}): JSX.Element {
    const person = side === 'orphan' ? link.orphan_person : link.anchor_person
    const distinctId = side === 'orphan' ? link.orphan_distinct_id : link.anchor_person_key
    const email = person?.email ?? extractEmail(distinctId)

    return (
        <div className="flex-1 min-w-0 rounded-lg border border-primary p-3">
            <div className="text-xs text-tertiary mb-1">{label}</div>
            <PersonDisplay person={linkPersonDisplay(person, distinctId)} noPopover withIcon="sm" />
            {!email && <div className="font-mono text-xs text-muted mt-1 truncate">{distinctId}</div>}
            <div className="mt-2 space-y-0.5 text-xs text-tertiary">
                {person?.first_seen && (
                    <div>
                        First seen{' '}
                        <span className="text-secondary">{dayjs(person.first_seen).format('MMM D, YYYY HH:mm')}</span>
                    </div>
                )}
                {person?.last_seen && (
                    <div>
                        Last seen{' '}
                        <span className="text-secondary">{dayjs(person.last_seen).format('MMM D, YYYY HH:mm')}</span>
                    </div>
                )}
            </div>
        </div>
    )
}

export function IdentityMatchingDetail({ link }: { link: IdentityMatchingLinkApi }): JSX.Element {
    const confidence = normalizedScore(link)
    const signals = extractSignals(link)
    const pct = Math.round(confidence * 100)
    const tagType = pct >= 70 ? 'success' : pct >= 40 ? 'warning' : 'default'
    const barColor = pct >= 70 ? 'bg-success' : pct >= 40 ? 'bg-warning' : 'bg-muted'

    return (
        <div className="space-y-4">
            {/* The match */}
            <div>
                <div className="flex items-center gap-3 mb-2">
                    <PersonCard label="Anonymous visitor" link={link} side="orphan" />
                    <IconArrowRight className="text-xl text-tertiary shrink-0" />
                    <PersonCard label="Identified person" link={link} side="anchor" />
                </div>
                <p className="text-sm text-secondary">{matchSummary(link, confidence)}</p>
            </div>

            {/* At a glance — the two persons' properties, side by side, for human validation */}
            <div className="rounded-lg border border-primary p-4">
                <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-semibold">At a glance</h4>
                    <span className="text-xs text-tertiary">Green = same value on both sides</span>
                </div>
                <div className={`${COMPARE_GRID} text-xs font-semibold text-tertiary border-b border-border pb-1 mb-1`}>
                    <span />
                    <span>Visitor</span>
                    <span>Person</span>
                </div>
                <div className="space-y-2">
                    <CompareSection title="Location & device" fields={PERSON_SIGNAL_FIELDS} link={link} />
                    <CompareSection title="Campaign" fields={PERSON_CAMPAIGN_FIELDS} link={link} />
                </div>
                {!link.orphan_person && !link.anchor_person && (
                    <p className="text-xs text-tertiary mt-1">
                        No person profiles were resolved for these distinct IDs, so there are no properties to compare.
                    </p>
                )}
            </div>

            {/* Why we matched — compact: one row per category, descriptions in tooltips */}
            <div>
                <h4 className="text-sm font-semibold mb-2">Why we matched them</h4>
                <div className="flex flex-col gap-1.5">
                    {CATEGORY_ORDER.map((category) => {
                        const catSignals = signals.filter((s) => s.category === category)
                        if (catSignals.length === 0) {
                            return null
                        }
                        return (
                            <div key={category} className="flex items-start gap-2">
                                <span className="text-xs text-tertiary w-20 shrink-0 pt-1">
                                    {CATEGORY_LABELS[category]}
                                </span>
                                <div className="flex flex-wrap gap-1">
                                    {catSignals.map((signal, i) => (
                                        <Tooltip
                                            key={i}
                                            title={`${STRENGTH_LABELS[signal.strength]} — ${signal.description}`}
                                        >
                                            <LemonTag type={CATEGORY_TAG_TYPE[category]}>{signal.label}</LemonTag>
                                        </Tooltip>
                                    ))}
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>

            {/* Confidence — compact single line */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs border-t border-border pt-3">
                <span className="flex items-center gap-2">
                    <span className="text-tertiary">Confidence</span>
                    <span className="inline-block w-20 h-1.5 rounded-full bg-bg-light overflow-hidden">
                        <span className={`block h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
                    </span>
                    <LemonTag type={tagType}>{pct}%</LemonTag>
                </span>
                <span className="flex items-center gap-1.5">
                    <span className="text-tertiary">Model</span>
                    <LemonTag>{link.model_version}</LemonTag>
                </span>
                <Tooltip title="The model's unnormalized score. For rules_v1 a weighted point sum; for logreg_v1 a 0–1 probability.">
                    <span>
                        <span className="text-tertiary">Raw score</span>{' '}
                        <span className="font-mono">{link.score.toFixed(2)}</span>
                    </span>
                </Tooltip>
                <Tooltip title="How much this score exceeds the next-best candidate. A larger gap means fewer competing matches.">
                    <span>
                        <span className="text-tertiary">Gap</span>{' '}
                        <span className="font-mono">{link.margin.toFixed(2)}</span>
                    </span>
                </Tooltip>
                <span>
                    <span className="text-tertiary">Computed</span>{' '}
                    {dayjs(link.computed_at).format('MMM D, YYYY HH:mm')}
                </span>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2">
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconExternal />}
                    to={urls.personByDistinctId(link.orphan_distinct_id)}
                >
                    View anonymous visitor
                </LemonButton>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconExternal />}
                    to={urls.personByDistinctId(link.anchor_person_key)}
                >
                    View identified person
                </LemonButton>
            </div>
        </div>
    )
}
