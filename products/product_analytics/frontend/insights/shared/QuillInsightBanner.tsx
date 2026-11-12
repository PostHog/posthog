import { ReactNode } from 'react'

import { IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface QuillInsightBannerProps {
    tone: 'info' | 'warning'
    children: ReactNode
    action?: { children: string; to: string; 'data-attr'?: string }
    onClose?: () => void
    className?: string
    'data-attr'?: string
}

export function QuillInsightBanner({
    tone,
    children,
    action,
    onClose,
    className,
    'data-attr': dataAttr,
}: QuillInsightBannerProps): JSX.Element {
    return (
        <Item variant="outline" size="sm" tone={tone} className={className} data-attr={dataAttr}>
            <ItemContent className="min-w-0">
                <Text size="xs" render={<div />}>
                    {children}
                </Text>
            </ItemContent>
            {(action || onClose) && (
                <ItemActions>
                    {action && (
                        <Button
                            variant="outline"
                            render={<LinkPrimitive to={action.to} />}
                            data-attr={action['data-attr']}
                        >
                            {action.children}
                        </Button>
                    )}
                    {onClose && (
                        <Button size="icon" aria-label="Close" tooltip="Close" onClick={onClose}>
                            <IconX />
                        </Button>
                    )}
                </ItemActions>
            )}
        </Item>
    )
}
