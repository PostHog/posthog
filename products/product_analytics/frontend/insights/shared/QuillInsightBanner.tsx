import { ReactNode } from 'react'

import { IconInfo, IconWarning, IconX } from '@posthog/icons'
import {
    Button,
    Callout,
    CalloutActions,
    CalloutClose,
    CalloutContent,
    CalloutDescription,
    CalloutIcon,
} from '@posthog/quill'

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
        <Callout tone={tone} className={className} data-attr={dataAttr}>
            <CalloutIcon>{tone === 'warning' ? <IconWarning /> : <IconInfo />}</CalloutIcon>
            <CalloutContent>
                <CalloutDescription className="text-xs">{children}</CalloutDescription>
            </CalloutContent>
            {action && (
                <CalloutActions>
                    <Button variant="outline" render={<LinkPrimitive to={action.to} />} data-attr={action['data-attr']}>
                        {action.children}
                    </Button>
                </CalloutActions>
            )}
            {onClose && (
                <CalloutClose tooltip="Dismiss" onClick={onClose}>
                    <IconX />
                </CalloutClose>
            )}
        </Callout>
    )
}
