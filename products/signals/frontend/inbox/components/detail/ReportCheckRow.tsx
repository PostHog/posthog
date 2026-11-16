import { IconClock, IconTrends } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { ReportCheckRowData } from './reportCheckPresentation'
import { ReportCheckTiming } from './ReportCheckTiming'

export function ReportCheckRow({
    row,
    cancelling,
    onCancel,
    onSuggestMetric,
    suggestionDisabledReason,
}: {
    row: ReportCheckRowData
    cancelling: boolean
    onCancel: (checkId: string) => void
    onSuggestMetric: () => void
    suggestionDisabledReason?: string | null
}): JSX.Element {
    const { check, reportStatus, tag, detail, cancelled, cancellable } = row

    return (
        <div
            className={`group flex flex-col gap-1 rounded border border-primary bg-surface-primary px-2.5 py-2 ${
                cancelled ? 'opacity-60' : ''
            }`}
        >
            <div className="flex flex-wrap items-start gap-2 min-w-0">
                <span className="mt-0.5 shrink-0 text-tertiary [&_svg]:size-3.5">
                    {check.kind === 'agent' ? <IconClock /> : <IconTrends />}
                </span>
                <Tooltip title={check.rationale || undefined}>
                    <span
                        className={`min-w-0 flex-1 basis-32 text-xs leading-snug text-default line-clamp-2 ${
                            cancelled ? 'line-through' : ''
                        }`}
                    >
                        {check.title}
                    </span>
                </Tooltip>
                <LemonTag size="small" type={tag.type} className="shrink-0">
                    {tag.label}
                </LemonTag>
            </div>
            <div className="min-w-0 pl-[1.375rem]">
                <span className="min-w-0 flex-1 text-xs leading-snug text-tertiary">
                    <ReportCheckTiming check={check} reportStatus={reportStatus} detail={detail} />
                </span>
            </div>
            {cancellable && (
                <div className="-mt-1 flex h-0 flex-wrap justify-end gap-1 overflow-hidden group-hover:mt-0 group-hover:h-auto group-focus-within:mt-0 group-focus-within:h-auto group-focus-within:overflow-visible [@media(hover:none)]:mt-0 [@media(hover:none)]:h-auto">
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        disabledReason={cancelling ? 'Canceling this check' : suggestionDisabledReason}
                        data-attr="signals-report-check-suggest-metric"
                        onClick={onSuggestMetric}
                    >
                        Suggest a better metric
                    </LemonButton>
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        status="danger"
                        loading={cancelling}
                        disabledReason={cancelling ? 'Canceling this check' : undefined}
                        data-attr="signals-report-check-stop"
                        // Pinned for existing autocapture dashboards.
                        onClick={() =>
                            LemonDialog.open({
                                title: 'Cancel this check?',
                                description: `This cancels future runs of "${check.title}". Results it already recorded stay on this report.`,
                                primaryButton: {
                                    children: 'Cancel this check',
                                    status: 'danger',
                                    onClick: () => onCancel(check.id),
                                },
                                secondaryButton: { children: 'Keep it' },
                            })
                        }
                    >
                        Cancel this check
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
