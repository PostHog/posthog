import { ReactNode } from 'react'

import { Heading, Text } from '@posthog/quill'

export function QuillConfigurationSubsection({
    title,
    titleExtra,
    description,
    children,
}: {
    title: string
    /** Rendered beside the title, for example a list of supported platforms. */
    titleExtra?: ReactNode
    description?: ReactNode
    children: ReactNode
}): JSX.Element {
    const heading = (
        <Heading size="sm" render={<h3 className="m-0" />}>
            {title}
        </Heading>
    )

    return (
        <div className="flex flex-col gap-2">
            {titleExtra ? (
                <div className="flex flex-wrap items-center gap-2">
                    {heading}
                    {titleExtra}
                </div>
            ) : (
                heading
            )}
            {description && (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {description}
                </Text>
            )}
            {children}
        </div>
    )
}
