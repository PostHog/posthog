import { useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconOpenSidebar } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import { ScannerTemplate, defaultScannerTemplates } from '../scannerTemplates'
import { ScannerType } from '../types'
import { CreateScannerButton } from './CreateScannerButton'
import { ScannerGoalDraft } from './ScannerGoalDraft'
import { TemplateCard } from './ScannerTemplatePicker'

// Test arms of the replay-vision-empty-state-experiment flag, keyed by the flag's variant key.
// The surface is the scanner list for a project that has never created a scanner; the goal metric
// is the backend's replay_vision_scanner_created event.
export type ScannerListEmptyStateVariant = 'templates' | 'example-observations'

const EMPTY_STATE_VARIANTS: readonly ScannerListEmptyStateVariant[] = ['templates', 'example-observations']

// Narrows a raw flag value to an empty-state variant. Control, booleans, and variant keys this
// build doesn't know yet all resolve to null (the pre-experiment empty state), so a flag/frontend
// version skew degrades to the control experience instead of rendering a broken arm.
export function scannerListEmptyStateVariant(flagValue: unknown): ScannerListEmptyStateVariant | null {
    return typeof flagValue === 'string' && (EMPTY_STATE_VARIANTS as readonly string[]).includes(flagValue)
        ? (flagValue as ScannerListEmptyStateVariant)
        : null
}

// Accessing the flag on kea's featureFlags proxy is what reports experiment exposure, so the read
// must stay behind every guard: exposure has to cover exactly the users who saw the empty state.
// Usage-tab visitors, renders before flags load (a stale read would log control and stick for the
// page view), and projects with scanners all resolve to null without touching the flag.
export function computeScannerListEmptyStateVariant({
    onScannersTab,
    receivedFeatureFlags,
    scannerStatsLoading,
    scannerTotal,
    featureFlags,
}: {
    onScannersTab: boolean
    receivedFeatureFlags: boolean
    scannerStatsLoading: boolean
    scannerTotal: number | undefined
    featureFlags: Record<string, unknown>
}): ScannerListEmptyStateVariant | null {
    if (!onScannersTab || !receivedFeatureFlags || scannerStatsLoading || scannerTotal !== 0) {
        return null
    }
    return scannerListEmptyStateVariant(featureFlags[FEATURE_FLAGS.REPLAY_VISION_EMPTY_STATE_EXPERIMENT])
}

const DOCS_LINK = (
    <Link
        to="https://posthog.com/docs/replay-vision?utm_medium=in-product&utm_campaign=empty-state-docs-link"
        target="_blank"
        className="inline-flex items-center gap-1"
    >
        How scanners work <IconOpenSidebar className="w-4 h-4" />
    </Link>
)

// The consent popover doesn't close on outside click, so the arm tracks which single AI entry
// point requested consent; opening one closes the rest instead of stacking popovers.
interface ConsentSlot {
    activeGate: string | null
    setActiveGate: (gateId: string | null) => void
}

// Unlike the picker page, this surface is reachable before the organization has approved AI data
// processing, so every AI entry point interposes the consent popover before its draft starts.
function ConsentGate({
    gateId,
    slot,
    children,
}: {
    gateId: string
    slot: ConsentSlot
    children: (gate: (proceed: () => void) => void) => JSX.Element
}): JSX.Element {
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const pendingStart = useRef<(() => void) | null>(null)

    return (
        <AIConsentPopoverWrapper
            placement="bottom"
            showArrow
            ignoreDismissal
            hideTrainingDisclaimer
            hidden={slot.activeGate !== gateId}
            onApprove={() => {
                slot.setActiveGate(null)
                pendingStart.current?.()
                pendingStart.current = null
            }}
            onDismiss={() => slot.setActiveGate(null)}
        >
            {children((proceed) => {
                if (dataProcessingAccepted) {
                    proceed()
                    return
                }
                pendingStart.current = proceed
                slot.setActiveGate(gateId)
            })}
        </AIConsentPopoverWrapper>
    )
}

function ConsentGatedTemplateCard({
    template,
    slot,
}: {
    template: ScannerTemplate | 'blank'
    slot: ConsentSlot
}): JSX.Element {
    const gateId = template === 'blank' ? 'template-blank' : `template-${template.key}`
    return (
        <ConsentGate gateId={gateId} slot={slot}>
            {(gate) => <TemplateCard template={template} gateStart={gate} />}
        </ConsentGate>
    )
}

function GatedGoalDraft({ className, slot }: { className?: string; slot: ConsentSlot }): JSX.Element {
    return (
        <div className={className}>
            <ConsentGate gateId="goal-draft" slot={slot}>
                {(gate) => <ScannerGoalDraft gateSubmit={gate} />}
            </ConsentGate>
        </div>
    )
}

function TemplatesEmptyState({ slot }: { slot: ConsentSlot }): JSX.Element {
    return (
        <div className="flex flex-col gap-6 pt-2" data-attr="vision-empty-state-templates">
            <div className="flex flex-col gap-2 text-center max-w-160 mx-auto">
                <h2 className="mb-0">Pick your first scanner</h2>
                <p className="text-secondary mb-0">
                    A scanner watches each new session recording and reports what it finds. Start from a template, then
                    adjust the prompt to fit your product.
                </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {defaultScannerTemplates.map((template) => (
                    <ConsentGatedTemplateCard key={template.key} template={template} slot={slot} />
                ))}
                <ConsentGatedTemplateCard template="blank" slot={slot} />
            </div>
            <GatedGoalDraft className="w-full max-w-160 mx-auto" slot={slot} />
            <div className="text-center">{DOCS_LINK}</div>
        </div>
    )
}

interface ExampleObservation {
    scannerType: ScannerType
    scannerName: string
    tag: { label: string; type: 'warning' | 'danger' } | null
    text: string
}

// Invented results covering three of the scanner types (a score, a tag, a summary), so the
// examples match what the create flow offers next. Static by design: an illustration, not data.
const EXAMPLE_OBSERVATIONS: ExampleObservation[] = [
    {
        scannerType: 'scorer',
        scannerName: 'Frustration score',
        tag: { label: '7/10', type: 'warning' },
        text: 'Clicked a disabled save button four times, reloaded the page, and re-entered the form before finishing signup.',
    },
    {
        scannerType: 'classifier',
        scannerName: 'Session outcome',
        tag: { label: 'blocked_by_error', type: 'danger' },
        text: 'Checkout failed twice with a card validation error. The user retried once, then left from the payment step.',
    },
    {
        scannerType: 'summarizer',
        scannerName: 'Session summary',
        tag: null,
        text: 'Compared the two paid plans, read the SSO docs, invited a teammate, and started a trial from the billing page.',
    },
]

function ExampleObservationsEmptyState({ slot }: { slot: ConsentSlot }): JSX.Element {
    return (
        <div
            className="flex flex-col md:flex-row gap-8 md:gap-12 pt-2 max-w-320 items-start"
            data-attr="vision-empty-state-example-observations"
        >
            <div className="flex flex-col gap-4 flex-1 max-w-140">
                <h2 className="mb-0">Create your first scanner</h2>
                <p className="mb-0">
                    Describe what to look for in plain language. A scanner watches each new session recording for it and
                    reports a score, a tag, or a summary.
                </p>
                <p className="mb-0">Every result is an event you can query, graph, and alert on.</p>
                <div className="flex items-center gap-4 flex-wrap mt-2">
                    <CreateScannerButton
                        acceptedLabel="Create your first scanner"
                        dataAttr="vision-scanner-create-empty"
                        size="medium"
                        consentRequested={slot.activeGate === 'create-button'}
                        onConsentRequestedChange={(requested) => slot.setActiveGate(requested ? 'create-button' : null)}
                    />
                    {DOCS_LINK}
                </div>
                <GatedGoalDraft className="mt-2" slot={slot} />
            </div>
            <div className="flex flex-col gap-3 flex-1 w-full max-w-160">
                <span className="text-muted text-xs font-semibold uppercase tracking-wide">Example results</span>
                {EXAMPLE_OBSERVATIONS.map((example) => (
                    <div
                        key={example.scannerName}
                        className="flex flex-col gap-2 bg-bg-light border border-border rounded p-4"
                    >
                        <div className="flex items-center gap-2">
                            <ScannerTypeBadge scannerType={example.scannerType} />
                            <span className="font-semibold text-sm">{example.scannerName}</span>
                            {example.tag && (
                                <LemonTag type={example.tag.type} className="ml-auto">
                                    {example.tag.label}
                                </LemonTag>
                            )}
                        </div>
                        <p className="text-sm text-secondary mb-0">{example.text}</p>
                    </div>
                ))}
            </div>
        </div>
    )
}

export function ScannerListEmptyState({ variant }: { variant: ScannerListEmptyStateVariant }): JSX.Element {
    const [activeGate, setActiveGate] = useState<string | null>(null)
    const slot: ConsentSlot = { activeGate, setActiveGate }
    return variant === 'templates' ? <TemplatesEmptyState slot={slot} /> : <ExampleObservationsEmptyState slot={slot} />
}
