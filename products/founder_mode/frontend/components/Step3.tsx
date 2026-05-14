import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { GTMSummaryApi, PricingTierApi, TargetSegmentApi } from '../generated/api.schemas'
import { founderLogic } from '../scenes/founderLogic'

export function Step3(): JSX.Element {
    const { currentProjectId, gtmResult, gtmStatus, gtmIsRunning, gtmError, gtmLoaded } = useValues(founderLogic)
    const { triggerGtm } = useActions(founderLogic)

    // Auto-fire GTM once the existing state has loaded and there's no result yet
    const autoFired = useRef(false)
    useEffect(() => {
        if (gtmLoaded && !autoFired.current && gtmStatus === 'idle' && currentProjectId) {
            autoFired.current = true
            triggerGtm()
        }
    }, [gtmLoaded, gtmStatus])

    if (!currentProjectId) {
        return (
            <LemonBanner type="info">
                Complete earlier stages first. GTM reads from your ideation and validation data.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <header className="flex items-baseline justify-between gap-3">
                <div>
                    <h2 className="text-xl font-semibold">Go-to-market</h2>
                    <p className="text-sm text-text-secondary mt-1">
                        Positioning, segments, pricing, and channels — grounded on your ideation and validation.
                    </p>
                </div>
                <LemonButton
                    icon={<IconRefresh />}
                    onClick={() => triggerGtm()}
                    disabledReason={gtmIsRunning ? 'GTM generation already running' : undefined}
                    type="secondary"
                    size="small"
                >
                    {gtmResult ? 'Re-run' : 'Run GTM'}
                </LemonButton>
            </header>

            {gtmIsRunning && (
                <div className="flex items-center gap-3 p-4 rounded-lg border border-border bg-bg-light">
                    <Spinner className="text-primary" />
                    <span className="text-sm text-text-secondary">
                        Generating your GTM strategy… this takes ~30-60 seconds
                    </span>
                </div>
            )}

            {gtmStatus === 'failed' && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => triggerGtm() }}>
                    {gtmError || 'GTM generation failed. Try again.'}
                </LemonBanner>
            )}

            {!gtmResult && !gtmIsRunning && gtmStatus !== 'failed' && gtmStatus !== 'idle' && (
                <LemonBanner type="info">
                    No GTM report yet. Hit "Run GTM" to generate your go-to-market strategy.
                </LemonBanner>
            )}

            {gtmResult && <GTMResultView result={gtmResult} />}
        </div>
    )
}

function GTMResultView({ result }: { result: GTMSummaryApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-5">
            <section className="border border-border rounded-lg p-4">
                <h3 className="font-semibold text-base mb-2">Positioning</h3>
                <p className="text-sm leading-relaxed">{result.positioning_statement}</p>
            </section>

            <section className="border border-border rounded-lg p-4">
                <h3 className="font-semibold text-base mb-3">Target segments</h3>
                <div className="flex flex-col gap-3">
                    <SegmentCard segment={result.primary_segment} label="Primary" />
                    {result.secondary_segments.map((seg, i) => (
                        <SegmentCard key={i} segment={seg} label="Secondary" />
                    ))}
                </div>
            </section>

            <div className="grid grid-cols-2 gap-4">
                <section className="border border-border rounded-lg p-4">
                    <h3 className="font-semibold text-base mb-2">Category</h3>
                    <p className="text-sm">{result.category}</p>
                </section>
                <section className="border border-border rounded-lg p-4">
                    <h3 className="font-semibold text-base mb-2">Moat</h3>
                    <p className="text-sm">{result.moat}</p>
                </section>
            </div>

            <section className="border border-border rounded-lg p-4">
                <h3 className="font-semibold text-base mb-2">Pricing</h3>
                <p className="text-sm text-text-secondary mb-3">{result.pricing_philosophy}</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {result.pricing_tiers.map((tier, i) => (
                        <PricingTierCard key={i} tier={tier} />
                    ))}
                </div>
            </section>

            <section className="border border-border rounded-lg p-4">
                <h3 className="font-semibold text-base mb-2">Channels</h3>
                <div className="flex flex-wrap gap-2">
                    <span className="text-xs font-semibold bg-primary/10 text-primary rounded-full px-3 py-1">
                        {result.primary_channel}
                    </span>
                    {result.secondary_channels.map((ch, i) => (
                        <span
                            key={i}
                            className="text-xs bg-bg-light text-text-secondary rounded-full px-3 py-1 border border-border"
                        >
                            {ch}
                        </span>
                    ))}
                </div>
            </section>
        </div>
    )
}

function SegmentCard({ segment, label }: { segment: TargetSegmentApi; label: string }): JSX.Element {
    return (
        <div className="bg-bg-light rounded-lg p-3">
            <div className="flex items-center gap-2 mb-1">
                <span className="text-[10px] uppercase tracking-wide font-semibold text-text-secondary">{label}</span>
                <span className="font-medium text-sm">{segment.name}</span>
            </div>
            <p className="text-sm text-text-secondary">{segment.description}</p>
            <p className="text-xs text-text-secondary mt-1 italic">{segment.why_reachable_now}</p>
        </div>
    )
}

function PricingTierCard({ tier }: { tier: PricingTierApi }): JSX.Element {
    return (
        <div className="bg-bg-light rounded-lg p-3">
            <div className="flex items-center justify-between mb-1">
                <span className="font-medium text-sm">{tier.name}</span>
                <span className="text-sm font-semibold text-primary">{tier.price}</span>
            </div>
            <p className="text-xs text-text-secondary">{tier.value}</p>
            <p className="text-[10px] text-text-secondary mt-1">→ {tier.target_segment}</p>
        </div>
    )
}
