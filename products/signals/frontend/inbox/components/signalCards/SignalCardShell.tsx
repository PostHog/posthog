import { createContext, useContext } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { ScoutLink } from 'lib/signals/ScoutLink'
import { scoutDisplayName, signalCardSourceLine } from 'lib/signals/signalCardSourceLine'
import type { SignalNode } from 'scenes/debug/signals/types'

import { getSourceProductMeta } from '../badges/sourceProductIcons'

interface SignalCardDisclosureState {
    expanded: boolean
    onChange: (expanded: boolean) => void
}

const SignalCardDisclosureContext = createContext<SignalCardDisclosureState | null>(null)

export function SignalCardDisclosureProvider({
    expanded,
    onChange,
    children,
}: SignalCardDisclosureState & { children: React.ReactNode }): JSX.Element {
    return (
        <SignalCardDisclosureContext.Provider value={{ expanded, onChange }}>
            {children}
        </SignalCardDisclosureContext.Provider>
    )
}

export function SignalCardHeader({
    signal,
    label,
    disclosure,
}: {
    signal: SignalNode
    /** Optional bold title shown after the source line (e.g. an entity name). */
    label?: React.ReactNode
    disclosure?: SignalCardDisclosureState | null
}): JSX.Element {
    const meta = getSourceProductMeta(signal.source_product)
    const Icon = meta?.Icon

    // Scout-authored findings link the scout's name to its detail page; everything else stays plain text.
    const scoutSkillName =
        signal.source_product === 'signals_scout'
            ? (signal.extra as { skill_name?: unknown } | undefined)?.skill_name
            : undefined
    const scoutName = typeof scoutSkillName === 'string' ? scoutDisplayName(scoutSkillName) : null

    return (
        <div
            className={disclosure && !disclosure.expanded ? 'flex items-center gap-2' : 'flex items-center gap-2 mb-2'}
        >
            {Icon ? (
                <span className="inline-flex shrink-0 items-center" aria-hidden>
                    <Icon className={`text-base ${meta.colorClass}`} />
                </span>
            ) : (
                <span className="size-2.5 rounded-full shrink-0 bg-border" />
            )}
            <span className="text-xs font-medium text-tertiary whitespace-nowrap">
                {scoutName && typeof scoutSkillName === 'string' ? (
                    <>
                        Scout · <ScoutLink skillName={scoutSkillName} className="text-tertiary" />
                    </>
                ) : (
                    signalCardSourceLine(signal)
                )}
                {' · '}
                <TZLabel time={signal.timestamp} />
            </span>
            {label && <span className="text-xs font-medium text-primary flex-1 truncate">{label}</span>}
            <span className="flex-1" />
            {disclosure ? (
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={disclosure.expanded ? <IconChevronDown /> : <IconChevronRight />}
                    aria-label={disclosure.expanded ? 'Collapse signal details' : 'Expand signal details'}
                    onClick={() => disclosure.onChange(!disclosure.expanded)}
                    className="shrink-0"
                />
            ) : null}
        </div>
    )
}

/** Bordered card container + shared header. Per-source cards render their body as `children`. */
export function SignalCardShell({
    signal,
    label,
    children,
}: {
    signal: SignalNode
    label?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    const disclosure = useContext(SignalCardDisclosureContext)

    return (
        <LemonCard hoverEffect={false} className={disclosure ? 'p-2 shadow-none' : 'p-3 shadow-sm'}>
            <SignalCardHeader signal={signal} label={label} disclosure={disclosure} />
            {!disclosure || disclosure.expanded ? children : null}
        </LemonCard>
    )
}
