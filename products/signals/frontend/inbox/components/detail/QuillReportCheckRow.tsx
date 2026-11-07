import { IconClock, IconTrends } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Badge,
    Button,
    Card,
    CardContent,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { quillBadgeVariant } from './quillBadgeVariant'
import { ReportCheckRowData } from './reportCheckPresentation'
import { reportCheckStopConfirmation } from './reportCheckStopConfirmation'
import { ReportCheckTiming } from './ReportCheckTiming'

/**
 * The quill sibling of `ReportCheckRow`. Cancel confirms first, because a canceled check is terminal.
 * The actions show on hover with a fine pointer, and stay visible on touch so they have a tap path.
 */
export function QuillReportCheckRow({
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
    const confirmation = reportCheckStopConfirmation(check)

    const title = (
        <Text
            size="xs"
            render={<span />}
            className={cn('min-w-0 flex-1 basis-32 leading-snug line-clamp-2', cancelled && 'line-through')}
        >
            {check.title}
        </Text>
    )

    return (
        <Card size="sm" className={cn('group', cancelled && 'opacity-60')}>
            <CardContent className="flex flex-col gap-1">
                <div className="flex min-w-0 flex-wrap items-start gap-2">
                    <span className="mt-0.5 shrink-0 text-subtle-foreground [&_svg]:size-3.5">
                        {check.kind === 'agent' ? <IconClock /> : <IconTrends />}
                    </span>
                    {check.rationale ? (
                        <Tooltip>
                            <TooltipTrigger render={title} />
                            <TooltipContent className="max-w-80">{check.rationale}</TooltipContent>
                        </Tooltip>
                    ) : (
                        title
                    )}
                    <Badge variant={quillBadgeVariant(tag.type)}>{tag.label}</Badge>
                </div>
                <div className="min-w-0 ps-5.5">
                    <Text size="xs" render={<span />} className="leading-snug text-subtle-foreground">
                        <ReportCheckTiming check={check} reportStatus={reportStatus} detail={detail} />
                    </Text>
                </div>
                {cancellable && (
                    <div className="flex flex-wrap justify-end gap-1 transition-opacity pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 pointer-fine:group-focus-within:opacity-100">
                        <Button
                            disabledReason={cancelling ? 'Canceling this check' : suggestionDisabledReason}
                            data-attr="signals-report-check-suggest-metric"
                            onClick={onSuggestMetric}
                        >
                            Suggest a better metric
                        </Button>
                        <AlertDialog>
                            <AlertDialogTrigger
                                render={
                                    <Button
                                        variant="destructive-outline"
                                        loading={cancelling}
                                        disabledReason={cancelling ? 'Canceling this check' : undefined}
                                        // Pinned for existing autocapture dashboards.
                                        data-attr="signals-report-check-stop"
                                    />
                                }
                            >
                                Cancel this check
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                                <AlertDialogHeader>
                                    <AlertDialogTitle>{confirmation.title}</AlertDialogTitle>
                                    <AlertDialogDescription>{confirmation.description}</AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                    <AlertDialogClose render={<Button variant="outline" />}>
                                        {confirmation.dismissLabel}
                                    </AlertDialogClose>
                                    <AlertDialogClose
                                        render={<Button variant="destructive-outline" />}
                                        onClick={() => onCancel(check.id)}
                                    >
                                        {confirmation.confirmLabel}
                                    </AlertDialogClose>
                                </AlertDialogFooter>
                            </AlertDialogContent>
                        </AlertDialog>
                    </div>
                )}
            </CardContent>
        </Card>
    )
}
