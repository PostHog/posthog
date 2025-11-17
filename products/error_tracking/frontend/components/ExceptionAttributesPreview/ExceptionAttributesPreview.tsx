import { Children } from 'react'
import { match } from 'ts-pattern'

import { IconBug } from '@posthog/icons'
import { LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { ExceptionAttributes } from 'lib/components/Errors/types'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'

export interface ExceptionAttributesPreviewProps {
    attributes: ExceptionAttributes | null
    loading?: boolean
    iconOnly?: boolean
}

export function ExceptionAttributesPreview({
    attributes,
    loading = false,
    iconOnly = false,
}: ExceptionAttributesPreviewProps): JSX.Element {
    return (
        <>
            {match(loading)
                .with(true, () => (
                    <span className="text-muted space-x-2 text-xs">
                        <Spinner />
                        <span>Loading details...</span>
                    </span>
                ))
                .with(
                    false,
                    () =>
                        attributes && (
                            <>
                                <PropertyWrapper title="Unhandled" visible={!attributes.handled}>
                                    <IconBug className="text-sm text-secondary" />
                                </PropertyWrapper>
                                <PropertyWrapper title={attributes.browser} visible={!!attributes.browser}>
                                    <Property property="$browser" title={attributes.browser} iconOnly={iconOnly} />
                                </PropertyWrapper>
                                <PropertyWrapper title={attributes.os} visible={!!attributes.os}>
                                    <Property property="$os" title={attributes.os} iconOnly={iconOnly} />
                                </PropertyWrapper>
                            </>
                        )
                )
                .exhaustive()}
        </>
    )
}

export function PropertyWrapper({
    title,
    visible = true,
    children,
}: {
    title?: string
    visible?: boolean
    children: JSX.Element
}): JSX.Element {
    if (Children.count(children) == 0 || title === undefined || !visible) {
        return <></>
    }
    return children
}

function Property({ property, title, iconOnly }: { property: string; title?: string; iconOnly: boolean }): JSX.Element {
    return iconOnly ? (
        <Tooltip title={title} delayMs={0}>
            <PropertyIcon property={property} value={title} className="text-sm text-secondary" />
        </Tooltip>
    ) : (
        <LemonTag className="bg-fill-primary">
            <PropertyIcon property={property} value={title} className="text-sm text-secondary" />
            <span className="capitalize">{title}</span>
        </LemonTag>
    )
}
