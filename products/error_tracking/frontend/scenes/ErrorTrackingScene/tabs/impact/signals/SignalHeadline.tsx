import { Text, cn } from 'lib/ui/quill'

export interface SignalHeadlineProps {
    value: string
    caption: string
    // Lenses that point at harm show their number in the status color.
    tone?: 'default' | 'destructive'
}

export function SignalHeadline({ value, caption, tone = 'default' }: SignalHeadlineProps): JSX.Element {
    return (
        <div className="flex min-w-0 items-baseline gap-1.5">
            <Text
                render={<span />}
                size="lg"
                weight="semibold"
                className={cn(
                    'shrink-0 whitespace-nowrap leading-none tabular-nums',
                    tone === 'destructive' && 'text-destructive-foreground'
                )}
            >
                {value}
            </Text>
            {/* The caption carries the meaning of the number, so it wraps at narrow widths instead of being cut off. */}
            <Text render={<span />} size="xs" variant="muted" className="min-w-0 line-clamp-2">
                {caption}
            </Text>
        </div>
    )
}
