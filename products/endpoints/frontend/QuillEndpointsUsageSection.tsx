import { ReactNode } from 'react'

import { Heading, Text } from '@posthog/quill'

export interface QuillEndpointsUsageSectionProps {
    title: string
    description: string
    /** The stat tiles of the section. They sit in a column beside the charts, and in a row above them when narrow. */
    tiles: ReactNode
    children: ReactNode
}

/** One step of the usage story: a heading, the numbers for the period, and the charts behind them. */
export function QuillEndpointsUsageSection({
    title,
    description,
    tiles,
    children,
}: QuillEndpointsUsageSectionProps): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <div className="flex flex-col">
                <Heading size="sm" render={<h2 />} className="m-0">
                    {title}
                </Heading>
                <Text size="xs" variant="muted" render={<p />} className="m-0">
                    {description}
                </Text>
            </div>
            <div className="grid grid-cols-1 gap-4 @min-[60rem]/main-content:grid-cols-3">
                {tiles}
                <div className="grid grid-cols-1 gap-4 @min-[48rem]/main-content:grid-cols-2 @min-[60rem]/main-content:col-span-2 [&>*:only-child]:col-span-full">
                    {children}
                </div>
            </div>
        </section>
    )
}
