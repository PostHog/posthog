import { Card, CardContent, CardFooter, ScrollArea, cn } from '@posthog/quill-primitives'

import type { WidgetCardProps } from '../WidgetCard'
import { quillCardBorderClass } from './quillCardBorder'

export function QuillWidgetCard({ body, bodyHeightClassName, footer, danger = false }: WidgetCardProps): JSX.Element {
    return (
        <Card size="sm" flush className={cn('w-full py-0', quillCardBorderClass(danger))}>
            {body && (
                // Product widgets keep PostHog's own colours inside the quill thread.
                <CardContent data-not-quill>
                    {/* The viewport inherits a `max-h-*` cap from the root, or it outgrows the root and scrolls nothing. */}
                    <ScrollArea className={bodyHeightClassName} viewportClassName="flex flex-col max-h-[inherit]">
                        {body}
                    </ScrollArea>
                </CardContent>
            )}
            <CardFooter data-not-quill className={cn('flex-col items-stretch gap-2 py-2', !body && 'border-t-0')}>
                {footer}
            </CardFooter>
        </Card>
    )
}
