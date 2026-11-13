import { Button, TableCell, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'

interface QuillFunnelTrendsValueCellProps {
    value: number
    isInProgress: boolean
    onOpenPersons?: () => void
}

export function QuillFunnelTrendsValueCell({
    value,
    isInProgress,
    onOpenPersons,
}: QuillFunnelTrendsValueCellProps): JSX.Element {
    const formatted = `${humanFriendlyNumber(value, 1)}%`
    const content = onOpenPersons ? (
        <Button
            variant={isInProgress ? 'link-muted' : 'link-foreground'}
            size="sm"
            className="-mx-2"
            onClick={onOpenPersons}
        >
            {formatted}
        </Button>
    ) : (
        formatted
    )

    return (
        <TableCell align="right" className="tabular-nums">
            {isInProgress ? (
                <Tooltip>
                    <TooltipTrigger render={<span className="text-muted-foreground" />}>{content}</TooltipTrigger>
                    <TooltipContent>This period is still in progress</TooltipContent>
                </Tooltip>
            ) : (
                content
            )}
        </TableCell>
    )
}
