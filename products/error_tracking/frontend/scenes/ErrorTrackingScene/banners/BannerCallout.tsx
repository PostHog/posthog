import { ComponentType, ReactNode } from 'react'

import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from 'lib/ui/quill'

import { BannerAction, BannerActionButton } from './BannerActionButton'
import { BannerDismissButton } from './BannerDismissButton'

export interface BannerCalloutProps {
    illustration: ComponentType<{ className?: string; loading?: 'lazy' | 'eager' }>
    title: string
    description: ReactNode
    primaryAction: BannerAction
    secondaryAction?: BannerAction
    /** Previous and next controls, when several banners are queued. */
    navigation?: ReactNode
    onDismiss: () => void
}

export function BannerCallout({
    illustration: Illustration,
    title,
    description,
    primaryAction,
    secondaryAction,
    navigation,
    onDismiss,
}: BannerCalloutProps): JSX.Element {
    return (
        // The shell uses the issues table's surface tokens, so the banner reads as a card in both themes.
        // Inside quill's scope these tokens resolve to the page background, so the shell stays outside it.
        <div className="@container rounded border border-primary bg-surface-primary">
            <Item className="flex-wrap border-transparent">
                {/* `eager` because a lazy image hidden by a container query never loads. */}
                <ItemMedia className="hidden @2xl:flex">
                    <Illustration className="size-12" loading="eager" />
                </ItemMedia>
                <ItemContent className="basis-72">
                    <ItemTitle>{title}</ItemTitle>
                    <ItemDescription>{description}</ItemDescription>
                </ItemContent>
                <ItemActions className="ml-auto flex-wrap">
                    {secondaryAction && <BannerActionButton action={secondaryAction} variant="default" />}
                    <BannerActionButton action={primaryAction} variant="primary" />
                    {navigation}
                    <BannerDismissButton onDismiss={onDismiss} />
                </ItemActions>
            </Item>
        </div>
    )
}
