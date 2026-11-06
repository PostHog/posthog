import { IconCheckCircle, IconCircleDashed, IconWarning } from '@posthog/icons'
import { LemonTag, Link, Spinner } from '@posthog/lemon-ui'

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

function stepCounts(step: ImportStepProgressApi): string {
    if (step.status === 'pending') {
        return 'Not started'
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

export function ProviderImportRunProgress({
    run,
    onOpenLink,
}: {
    run: ProviderImportRunApi
    onOpenLink?: () => void
}): JSX.Element {
    return (
        <ul className="flex flex-col gap-3 m-0 p-0 list-none" data-attr={`${run.provider}-import-run-progress`}>
            {run.steps.map((step) => (
                <li key={step.key} className="flex flex-col gap-1">
                    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                        <span className="flex items-center gap-2 font-medium">
                            {STEP_ICONS[step.status]}
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
                    {step.warnings.length > 0 && (
                        <ul className="m-0 ml-6 pl-0 list-none flex flex-col gap-0.5 text-xs text-secondary">
                            {step.warnings.map((warning) => (
                                <li key={warning}>{warning}</li>
                            ))}
                            {step.warnings_omitted > 0 && (
                                <li>And {step.warnings_omitted.toLocaleString()} more like these.</li>
                            )}
                        </ul>
                    )}
                    {step.items.length > 0 && (
                        <ul className="m-0 ml-6 pl-0 list-none max-h-60 overflow-y-auto divide-y divide-border">
                            {step.items.map((item, index) => (
                                <ItemRow key={`${item.label}-${index}`} item={item} onOpenLink={onOpenLink} />
                            ))}
                            {step.items_omitted > 0 && (
                                <li className="py-1.5 text-xs text-secondary">
                                    And {step.items_omitted.toLocaleString()} more.
                                </li>
                            )}
                        </ul>
                    )}
                </li>
            ))}
        </ul>
    )
}
