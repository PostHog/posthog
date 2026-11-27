import { useState } from 'react'

import { IconCheckCircle, IconCircleDashed, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import type {
    ImportStepItemApi,
    ImportStepProgressApi,
    ImportStepStatusEnumApi,
    ProviderImportRunApi,
} from 'products/messaging/frontend/generated/api.schemas'

const STEP_ICONS: Record<ImportStepStatusEnumApi, JSX.Element> = {
    pending: <IconCircleDashed className="text-muted text-base shrink-0" />,
    running: <Spinner className="text-base shrink-0" />,
    completed: <IconCheckCircle className="text-success text-base shrink-0" />,
    failed: <IconWarning className="text-danger text-base shrink-0" />,
}

const ITEM_STATUS_TAGS: Record<ImportStepItemApi['status'], JSX.Element | null> = {
    created: <LemonTag type="success">Imported</LemonTag>,
    skipped: <LemonTag>Left as it is</LemonTag>,
    failed: <LemonTag type="danger">Failed</LemonTag>,
    listed: null,
}

const SKIPPED_ICON = <IconWarning className="text-warning text-base shrink-0" />

function isSkipped(step: ImportStepProgressApi): boolean {
    return step.status === 'completed' && step.skipped
}

function stepCounts(step: ImportStepProgressApi): string {
    if (step.status === 'pending') {
        return 'Not started'
    }
    if (isSkipped(step)) {
        return 'Skipped'
    }
    return `${step.processed.toLocaleString()} read · ${step.imported.toLocaleString()} new or changed`
}

function ItemRow({ item, onOpenLink }: { item: ImportStepItemApi; onOpenLink?: () => void }): JSX.Element {
    return (
        <li className="flex flex-col gap-0.5 py-1.5">
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                <span className="min-w-0 break-words font-medium line-clamp-2">
                    {item.url ? (
                        <Link to={item.url} onClick={onOpenLink}>
                            {item.label}
                        </Link>
                    ) : (
                        item.label
                    )}
                </span>
                {ITEM_STATUS_TAGS[item.status]}
            </div>
            {item.notes.map((note) => (
                <div key={note} className="text-xs text-secondary break-words">
                    {note}
                </div>
            ))}
        </li>
    )
}

// The window scrolls as a whole, so a long list shows its first rows until the person asks for the rest.
const COLLAPSED_ITEM_COUNT = 5

function StepItems({ step, onOpenLink }: { step: ImportStepProgressApi; onOpenLink?: () => void }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const shown = expanded ? step.items : step.items.slice(0, COLLAPSED_ITEM_COUNT)
    const hidden = step.items.length - shown.length

    return (
        <ul className="m-0 ml-6 pl-0 list-none divide-y divide-border">
            {shown.map((item, index) => (
                <ItemRow key={`${item.label}-${index}`} item={item} onOpenLink={onOpenLink} />
            ))}
            {hidden > 0 && (
                <li className="py-1">
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={() => setExpanded(true)}
                        data-attr={`${step.key}-import-items-show-all`}
                    >
                        Show {hidden.toLocaleString()} more
                    </LemonButton>
                </li>
            )}
            {step.items_omitted > 0 && (
                <li className="py-1.5 text-xs text-secondary">And {step.items_omitted.toLocaleString()} more.</li>
            )}
        </ul>
    )
}

// A skipped step's first warning says why. Steps skipped for the same reason share one line.
function SkippedStepsBanner({ steps }: { steps: ImportStepProgressApi[] }): JSX.Element | null {
    const byReason = new Map<string, string[]>()
    for (const step of steps.filter(isSkipped)) {
        const reason = step.warnings[0] ?? ''
        byReason.set(reason, [...(byReason.get(reason) ?? []), step.label])
    }
    if (byReason.size === 0) {
        return null
    }
    return (
        <LemonBanner type="warning">
            <ul className="m-0 pl-0 list-none flex flex-col gap-1">
                {[...byReason].map(([reason, labels]) => (
                    <li key={reason}>
                        <span className="font-semibold">{labels.join(', ')}:</span> {reason || 'Skipped.'}
                    </li>
                ))}
            </ul>
        </LemonBanner>
    )
}

export function ProviderImportRunProgress({
    run,
    onOpenLink,
}: {
    run: ProviderImportRunApi
    onOpenLink?: () => void
}): JSX.Element {
    return (
        <>
            <SkippedStepsBanner steps={run.steps} />
            <ul className="flex flex-col gap-3 m-0 p-0 list-none" data-attr={`${run.provider}-import-run-progress`}>
                {run.steps.map((step) => (
                    <ProviderImportStep key={step.key} step={step} onOpenLink={onOpenLink} />
                ))}
            </ul>
        </>
    )
}

function ProviderImportStep({
    step,
    onOpenLink,
}: {
    step: ImportStepProgressApi
    onOpenLink?: () => void
}): JSX.Element {
    const skipped = isSkipped(step)
    // The banner above the steps already shows why a step was skipped.
    const warnings = skipped ? step.warnings.slice(1) : step.warnings
    return (
        <li className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                <span className="flex items-center gap-2 font-medium">
                    {skipped ? SKIPPED_ICON : STEP_ICONS[step.status]}
                    <span>{step.label}</span>
                </span>
                <span className="text-xs text-secondary" translate="no">
                    {stepCounts(step)}
                </span>
            </div>
            {step.last_error && (
                <div className={`ml-6 text-xs ${step.status === 'failed' ? 'text-danger' : 'text-warning'}`}>
                    {step.status === 'failed' ? step.last_error : `Retrying after an error: ${step.last_error}`}
                </div>
            )}
            {step.counts.length > 0 && (
                <dl className="m-0 ml-6 flex flex-col gap-0.5 text-xs">
                    {step.counts.map((count) => (
                        <div key={count.key} className="flex justify-between gap-4">
                            <dt className="text-secondary font-normal">{count.label}</dt>
                            <dd className="m-0 font-medium">{count.value.toLocaleString()}</dd>
                        </div>
                    ))}
                </dl>
            )}
            {warnings.length > 0 && (
                <ul className="m-0 ml-6 pl-0 list-none flex flex-col gap-0.5 text-xs text-secondary">
                    {warnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                    ))}
                    {step.warnings_omitted > 0 && (
                        <li>And {step.warnings_omitted.toLocaleString()} more like these.</li>
                    )}
                </ul>
            )}
            {step.items.length > 0 && <StepItems step={step} onOpenLink={onOpenLink} />}
        </li>
    )
}
