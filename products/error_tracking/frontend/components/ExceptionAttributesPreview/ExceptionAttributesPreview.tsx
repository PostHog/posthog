import { Children } from 'react'
import { match } from 'ts-pattern'

import { IconBug } from '@posthog/icons'
import { LemonTag, Spinner } from '@posthog/lemon-ui'

import { ExceptionAttributes } from 'lib/components/Errors/types'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'

export interface ExceptionAttributesPreviewProps {
    attributes: ExceptionAttributes | null
    loading?: boolean
}

export function ExceptionAttributesPreview({
    attributes,
    loading = false,
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
                                    <PropertyIcon
                                        property="$browser"
                                        value={attributes.browser}
                                        className="text-sm text-secondary"
                                    />
                                </PropertyWrapper>
                                <PropertyWrapper title={attributes.os} visible={!!attributes.os}>
                                    <PropertyIcon
                                        property="$os"
                                        value={attributes.os}
                                        className="text-sm text-secondary"
                                    />
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
    return (
        <LemonTag className="bg-fill-primary">
            {children}
            <span className="capitalize">{title}</span>
        </LemonTag>
    )
}
