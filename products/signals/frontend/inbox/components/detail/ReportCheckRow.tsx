import { IconClock, IconTrends } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { ReportCheckRowData } from './reportCheckPresentation'

/**
 * One follow-up check on the report rail: what it claims, where it stands, and the one thing a
 * reader can still do about it. The Stop button appears on hover and confirms first, because a
 * cancelled check is terminal and its author has to write a new one to get the answer back.
 */
export function ReportCheckRow({
    row,
    cancelling,
    onCancel,
}: {
    row: ReportCheckRowData
    cancelling: boolean
    onCancel: (checkId: string) => void
}): JSX.Element {
    const { check, tag, detail, cancelled, cancellable } = row

    return (
        <div
            className={`group flex flex-col gap-1 rounded border border-primary bg-surface-primary px-2.5 py-2 ${
                cancelled ? 'opacity-60' : ''
            }`}
        >
            <div className="flex items-start gap-2 min-w-0">
                <span className="mt-0.5 shrink-0 text-tertiary [&_svg]:size-3.5">
                    {check.kind === 'agent' ? <IconClock /> : <IconTrends />}
                </span>
                <Tooltip title={check.rationale || undefined}>
                    <span
                        className={`min-w-0 flex-1 text-xs leading-snug text-default line-clamp-2 ${
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
            <div className="flex items-end gap-2 min-w-0 pl-[1.375rem]">
                <span className="min-w-0 flex-1 text-xs leading-snug text-tertiary">{detail}</span>
                {cancellable && (
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        status="danger"
                        loading={cancelling}
                        disabledReason={cancelling ? 'Stopping this check' : undefined}
                        data-attr="signals-report-check-stop"
                        className="shrink-0 opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100"
                        onClick={() =>
                            LemonDialog.open({
                                title: 'Stop this check?',
                                description: `"${check.title}" will not run, and nothing will report back on it. Results it already recorded stay on this report.`,
                                primaryButton: {
                                    children: 'Stop check',
                                    status: 'danger',
                                    onClick: () => onCancel(check.id),
                                },
                                secondaryButton: { children: 'Keep it' },
                            })
                        }
                    >
                        Stop
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
