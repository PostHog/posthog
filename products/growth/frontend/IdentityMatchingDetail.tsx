import { IconArrowRight, IconBrowser, IconExternal, IconGlobe, IconLaptop, IconTarget } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import type { IdentityMatchingLinkApi } from './generated/api.schemas'
import {
    CATEGORY_DESCRIPTIONS,
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    type Signal,
    type SignalCategory,
    extractEmail,
    extractSignals,
    normalizedScore,
    personFromDistinctId,
} from './identityMatchingUtils'

const CATEGORY_ICON: Record<SignalCategory, JSX.Element> = {
    network: <IconGlobe />,
    device: <IconLaptop />,
    behavior: <IconBrowser />,
    attribution: <IconTarget />,
}

const STRENGTH_LABELS: Record<number, string> = {
    1: 'Weak signal',
    2: 'Moderate signal',
    3: 'Strong signal',
}

function matchSummary(link: IdentityMatchingLinkApi, confidence: number): string {
    const signals = extractSignals(link)
    const topSignals = signals.filter((s) => s.strength >= 2).slice(0, 2)
    const reasons = topSignals.map((s) => s.label.toLowerCase()).join(' and ')
    const pct = Math.round(confidence * 100)
    const personLabel = extractEmail(link.anchor_person_key) ?? 'this identified person'
    if (reasons) {
        return `We're ${pct}% confident this anonymous visitor is ${personLabel}, because they ${reasons}.`
    }
    return `We're ${pct}% confident this anonymous visitor is ${personLabel}.`
}

function SignalRow({ signal }: { signal: Signal }): JSX.Element {
    return (
        <div className="flex items-start gap-2 py-1.5">
            <Tooltip title={STRENGTH_LABELS[signal.strength]}>
                <div className="flex shrink-0 pt-0.5">
                    {Array.from({ length: 3 }, (_, i) => (
                        <div
                            key={i}
                            className={`size-1.5 rounded-full mr-0.5 ${
                                i < signal.strength ? 'bg-accent' : 'bg-border'
                            }`}
                        />
                    ))}
                </div>
            </Tooltip>
            <div className="min-w-0">
                <span className="text-sm font-medium">{signal.label}</span>
                <p className="text-xs text-tertiary mt-0.5">{signal.description}</p>
            </div>
        </div>
    )
}

function EvidenceSection({ category, signals }: { category: SignalCategory; signals: Signal[] }): JSX.Element | null {
    if (signals.length === 0) {
        return null
    }
    return (
        <div>
            <div className="flex items-center gap-2 mb-2">
                <span className="text-base text-secondary">{CATEGORY_ICON[category]}</span>
                <h4 className="text-sm font-semibold">{CATEGORY_LABELS[category]}</h4>
            </div>
            <p className="text-xs text-tertiary mb-2">{CATEGORY_DESCRIPTIONS[category]}</p>
            <div className="divide-y divide-border">
                {signals.map((signal, i) => (
                    <SignalRow key={i} signal={signal} />
                ))}
            </div>
        </div>
    )
}

export function IdentityMatchingDetail({ link }: { link: IdentityMatchingLinkApi }): JSX.Element {
    const confidence = normalizedScore(link)
    const signals = extractSignals(link)
    const orphanEmail = extractEmail(link.orphan_distinct_id)
    const anchorEmail = extractEmail(link.anchor_person_key)
    const pct = Math.round(confidence * 100)

    return (
        <div className="space-y-6">
            {/* The match */}
            <div>
                <div className="flex items-center gap-4 mb-3">
                    <div className="flex-1 rounded-lg border border-primary p-3">
                        <div className="text-xs text-tertiary mb-1">Anonymous visitor</div>
                        <PersonDisplay person={personFromDistinctId(link.orphan_distinct_id)} noPopover withIcon="sm" />
                        {!orphanEmail && (
                            <div className="font-mono text-xs text-muted mt-1">{link.orphan_distinct_id}</div>
                        )}
                    </div>
                    <IconArrowRight className="text-xl text-tertiary shrink-0" />
                    <div className="flex-1 rounded-lg border border-primary p-3">
                        <div className="text-xs text-tertiary mb-1">Identified person</div>
                        <PersonDisplay person={personFromDistinctId(link.anchor_person_key)} noPopover withIcon="sm" />
                        {!anchorEmail && (
                            <div className="font-mono text-xs text-muted mt-1">{link.anchor_person_key}</div>
                        )}
                    </div>
                </div>
                <p className="text-sm text-secondary">{matchSummary(link, confidence)}</p>
            </div>

            {/* Confidence */}
            <div className="rounded-lg border border-primary p-4">
                <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-semibold">Confidence assessment</h4>
                    <LemonTag
                        type={pct >= 70 ? 'success' : pct >= 40 ? 'warning' : 'default'}
                    >{`${pct}% confident`}</LemonTag>
                </div>
                <div className="flex items-center gap-2 mb-3">
                    <div className="flex-1 h-2 rounded-full bg-bg-light overflow-hidden">
                        <div
                            className={`h-full rounded-full ${
                                pct >= 70 ? 'bg-success' : pct >= 40 ? 'bg-warning' : 'bg-muted'
                            }`}
                            style={{ width: `${pct}%` }}
                        />
                    </div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>
                        <span className="text-tertiary">Model</span>
                        <div className="mt-0.5">
                            <LemonTag>{link.model_version}</LemonTag>
                        </div>
                    </div>
                    <div>
                        <span className="text-tertiary">Confidence gap</span>
                        <Tooltip title="How much this score exceeds the next-best candidate. A larger gap means fewer competing matches.">
                            <div className="mt-0.5 font-mono">{link.margin.toFixed(2)}</div>
                        </Tooltip>
                    </div>
                    <div>
                        <span className="text-tertiary">Raw score</span>
                        <Tooltip title="The model's unnormalized score. For rules_v1 this is a weighted point sum; for logreg_v1 it's a 0–1 probability.">
                            <div className="mt-0.5 font-mono">{link.score.toFixed(2)}</div>
                        </Tooltip>
                    </div>
                    <div>
                        <span className="text-tertiary">Computed</span>
                        <div className="mt-0.5">{dayjs(link.computed_at).format('MMM D, YYYY HH:mm')}</div>
                    </div>
                </div>
            </div>

            {/* Evidence by category */}
            <div className="space-y-5">
                <h4 className="text-sm font-semibold">Why we matched them</h4>
                {CATEGORY_ORDER.map((category) => {
                    const catSignals = signals.filter((s) => s.category === category)
                    return <EvidenceSection key={category} category={category} signals={catSignals} />
                })}
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2 pt-2 border-t border-border">
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
