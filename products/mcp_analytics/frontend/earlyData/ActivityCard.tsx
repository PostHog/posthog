import { ComponentType, ReactNode } from 'react'

import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from 'lib/ui/quill'

import {
    BannerAction,
    BannerActionButton,
} from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/banners/BannerActionButton'
import { BannerDismissButton } from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/banners/BannerDismissButton'

export interface ActivityCardProps {
    illustration: ComponentType<{ className?: string; loading?: 'lazy' | 'eager' }>
    title: ReactNode
    description: ReactNode
    primaryAction?: BannerAction
    /** Replaces primaryAction, e.g. a button with a menu. */
    primaryControl?: ReactNode
    secondaryAction?: BannerAction
    navigation?: ReactNode
    onDismiss: () => void
}

export function ActivityCard({
    illustration: Illustration,
    title,
    description,
    primaryAction,
    primaryControl,
    secondaryAction,
    navigation,
    onDismiss,
}: ActivityCardProps): JSX.Element {
    return (
        // Surface tokens resolve wrong inside quill, so the shell stays outside it.
        <div className="@container rounded border border-primary bg-surface-primary">
            <Item className="items-start border-transparent">
                {/* `eager` because a lazy image hidden by a container query never loads. */}
                <ItemMedia className="hidden @xl:flex">
                    <Illustration className="size-12" loading="eager" />
                </ItemMedia>
                <ItemContent>
                    <ItemTitle>{title}</ItemTitle>
                    <ItemDescription>{description}</ItemDescription>
                    {primaryAction || primaryControl || secondaryAction ? (
                        <div className="mt-2 flex flex-wrap items-center gap-1">
                            {primaryControl ??
                                (primaryAction && <BannerActionButton action={primaryAction} variant="primary" />)}
                            {secondaryAction && <BannerActionButton action={secondaryAction} variant="default" />}
                        </div>
                    ) : null}
                </ItemContent>
                <ItemActions className="self-start">
                    {navigation}
                    <BannerDismissButton onDismiss={onDismiss} />
                </ItemActions>
            </Item>
        </div>
    )
}
