import type { ComponentType } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { HoggiePngProps } from 'lib/brand/hoggies'

export interface HedgehogTipCardLink {
    label: string
    to: string
    dataAttr: string
    onClick?: () => void
}

export function HedgehogTipCard({
    Hedgehog,
    title,
    body,
    link,
}: {
    Hedgehog: ComponentType<Pick<HoggiePngProps, 'className' | 'loading'>>
    title: string
    body: string
    link: HedgehogTipCardLink
}): JSX.Element {
    return (
        <div className="@container flex items-start gap-4 rounded border border-primary bg-surface-primary p-4">
            {/* Eager because a lazy image in `display: none` never gets fetched. */}
            <Hedgehog className="hidden w-20 shrink-0 @min-[22rem]:block" loading="eager" />
            <div className="flex min-w-0 flex-1 flex-col items-start gap-1 text-sm">
                <span className="text-base font-semibold">{title}</span>
                <span className="text-secondary">{body}</span>
                <LemonButton
                    className="mt-2"
                    size="small"
                    type="secondary"
                    to={link.to}
                    targetBlank
                    sideIcon={<IconExternal />}
                    onClick={link.onClick}
                    data-attr={link.dataAttr}
                >
                    {link.label}
                </LemonButton>
            </div>
        </div>
    )
}
