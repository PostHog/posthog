import { IconInfo } from '@posthog/icons'
import {
    Button,
    Card,
    CardAction,
    CardContent,
    CardFooter,
    CardHeader,
    CardTitle,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

export interface AiVisibilityCardProps {
    title?: string
    /** How to read the tile, shown from an info button next to the title rather than as a footer under the data. */
    description?: string
    actions?: React.ReactNode
    footer?: React.ReactNode
    className?: string
    children: React.ReactNode
}

/** A tile in AI visibility: an optional title row with its actions, the content, and an optional footer note. */
export function AiVisibilityCard({
    title,
    description,
    actions,
    footer,
    className,
    children,
}: AiVisibilityCardProps): JSX.Element {
    return (
        <Card size="sm" className={cn('min-w-0', className)}>
            {title ? (
                <CardHeader>
                    <CardTitle className="flex min-h-6 items-center gap-1">
                        {title}
                        {description ? (
                            <Tooltip>
                                <TooltipTrigger
                                    delay={0}
                                    render={<Button size="icon-xs" aria-label={`About ${title}`} />}
                                >
                                    <IconInfo />
                                </TooltipTrigger>
                                <TooltipContent className="max-w-80">{description}</TooltipContent>
                            </Tooltip>
                        ) : null}
                    </CardTitle>
                    {actions ? (
                        // Quill's action spans two rows for a description; without one, the second row would only add height.
                        <CardAction className="row-span-1 flex flex-wrap items-center gap-2">{actions}</CardAction>
                    ) : null}
                </CardHeader>
            ) : null}
            <CardContent className="flex min-h-0 flex-1 flex-col">{children}</CardContent>
            {footer ? (
                <CardFooter>
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        {footer}
                    </Text>
                </CardFooter>
            ) : null}
        </Card>
    )
}
