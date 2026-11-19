// PROTOTYPE (throwaway): a titled card that holds one chart or one insight on overview B2.
import clsx from 'clsx'

import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@posthog/quill'

export function ChartCard({
    title,
    description,
    action,
    className,
    children,
}: {
    title: string
    description?: string
    action?: React.ReactNode
    className?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <Card className={clsx('min-w-0', className)}>
            <CardHeader>
                <CardTitle>{title}</CardTitle>
                {description ? <CardDescription>{description}</CardDescription> : null}
                {action ? <CardAction>{action}</CardAction> : null}
            </CardHeader>
            <CardContent>{children}</CardContent>
        </Card>
    )
}
