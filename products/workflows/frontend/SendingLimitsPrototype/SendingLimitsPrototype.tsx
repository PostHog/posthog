// PROTOTYPE (branch prototype/sending-limits-ux): throwaway, never merge.
// Question: what should a customer see about their email sending limit? Four variants (A hide it,
// B explain it, C at broadcast time, D check at sender setup) over three surfaces and five states.
// URL params: ?variant=A|B|C|D&surface=setup|reputation|broadcast&state=new|warming|capped|moved-down|blocked
import { useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { PrototypeSwitcher } from './PrototypeSwitcher'
import {
    DOMAIN_CHECKS,
    DomainProfileKey,
    STATES,
    SURFACES,
    StateKey,
    SurfaceKey,
    VARIANTS,
    VARIANT_USAGE_FLAGS,
    VariantKey,
} from './sendingLimitsPrototypeData'
import { VariantAHide } from './VariantAHide'
import { VariantBExplain } from './VariantBExplain'
import { VariantCBroadcast } from './VariantCBroadcast'
import { VariantDSetupCheck } from './VariantDSetupCheck'
import { VariantMix } from './VariantMix'

function readParam<T extends string>(name: string, allowed: readonly T[], fallback: T): T {
    const value = new URLSearchParams(window.location.search).get(name)
    return allowed.includes(value as T) ? (value as T) : fallback
}

function writeParam(name: string, value: string): void {
    const url = new URL(window.location.href)
    url.searchParams.set(name, value)
    window.history.replaceState(null, '', url.toString())
}

function useUrlState<T extends string>(name: string, allowed: readonly T[], fallback: T): [T, (value: T) => void] {
    const [value, setValue] = useState<T>(() => readParam(name, allowed, fallback))
    return [
        value,
        (next: T) => {
            writeParam(name, next)
            setValue(next)
        },
    ]
}

const VARIANT_KEYS = VARIANTS.map((variant) => variant.key)
const SURFACE_KEYS = SURFACES.map((surface) => surface.key)
const STATE_KEYS = Object.keys(STATES) as StateKey[]
const DOMAIN_KEYS = Object.keys(DOMAIN_CHECKS) as DomainProfileKey[]

export function SendingLimitsPrototype(): JSX.Element {
    const [variant, setVariant] = useUrlState<VariantKey>('variant', VARIANT_KEYS, 'A')
    const [surface, setSurface] = useUrlState<SurfaceKey>('surface', SURFACE_KEYS, 'broadcast')
    const [stateKey, setStateKey] = useUrlState<StateKey>('state', STATE_KEYS, 'capped')
    const [domainProfile, setDomainProfile] = useUrlState<DomainProfileKey>('domain', DOMAIN_KEYS, 'starter')
    const state = STATES[stateKey]
    const primarySurface = VARIANTS.find((v) => v.key === variant)?.primarySurface

    const switcherVariants = VARIANTS.map((v) => ({
        key: v.key,
        label: `${v.key} (${v.name})`,
        detail: VARIANT_USAGE_FLAGS[v.key],
    }))

    return (
        <div className="min-h-screen pb-24">
            <div className="border-b border-dashed bg-surface-secondary px-4 py-3 flex flex-col gap-2 sticky top-0 z-40">
                <div className="flex flex-wrap items-center gap-4">
                    <span className="text-xs font-semibold uppercase text-secondary">Prototype · sending limits</span>
                    <LemonSegmentedButton
                        size="small"
                        value={surface}
                        onChange={setSurface}
                        options={SURFACES.map((s) => ({
                            value: s.key,
                            label: s.key === primarySurface ? `${s.label} ★` : s.label,
                        }))}
                    />
                    <LemonSegmentedButton
                        size="small"
                        value={stateKey}
                        onChange={setStateKey}
                        options={STATE_KEYS.map((key) => ({ value: key, label: STATES[key].label }))}
                    />
                </div>
                <div className="text-xs text-secondary">
                    Fake data: allowance {humanFriendlyNumber(state.allowancePerDay)}/day · sent today{' '}
                    {humanFriendlyNumber(state.sentToday)} · waiting {humanFriendlyNumber(state.queued)} · 7-day bounces{' '}
                    {percentage(state.rates7d.bounce, 1, true)}, complaints{' '}
                    {percentage(state.rates7d.complaint, 2, true)} · 30-day bounces{' '}
                    {percentage(state.rates30d.bounce, 1, true)} · broadcast{' '}
                    {humanFriendlyNumber(state.broadcast.sentSoFar)}/{humanFriendlyNumber(state.broadcast.audience)}
                    {state.broadcast.sample ? ` · sample ${state.broadcast.sample.verdict}` : ''} · ★ main surface of
                    this variant
                </div>
            </div>
            <div className="p-6">
                {variant === 'A' && <VariantAHide surface={surface} state={state} />}
                {variant === 'B' && <VariantBExplain surface={surface} state={state} />}
                {variant === 'C' && <VariantCBroadcast surface={surface} state={state} />}
                {variant === 'D' && (
                    <VariantDSetupCheck
                        surface={surface}
                        state={state}
                        domainProfile={domainProfile}
                        setDomainProfile={setDomainProfile}
                    />
                )}
                {variant === 'Mix' && (
                    <VariantMix
                        surface={surface}
                        state={state}
                        domainProfile={domainProfile}
                        setDomainProfile={setDomainProfile}
                    />
                )}
            </div>
            <PrototypeSwitcher
                variants={switcherVariants}
                current={variant}
                onChange={(key) => setVariant(key as VariantKey)}
            />
        </div>
    )
}
