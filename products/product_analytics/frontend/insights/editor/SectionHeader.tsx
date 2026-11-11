import { ReactNode } from 'react'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

export function SectionHeader({
    children,
    tooltip,
    dataAttr,
}: {
    children: ReactNode
    tooltip?: string
    dataAttr?: string
}): JSX.Element {
    return (
        <h5 className="mx-2 my-1" data-attr={dataAttr}>
            {children}
            {tooltip && (
                <>
                    {' '}
                    <Tooltip title={tooltip}>
                        <IconInfo className="relative top-0.5 text-lg text-secondary" />
                    </Tooltip>
                </>
            )}
        </h5>
    )
}
