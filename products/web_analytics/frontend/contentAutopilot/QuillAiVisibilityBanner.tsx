import {
    Button,
    Callout,
    CalloutActions,
    CalloutClose,
    CalloutContent,
    CalloutDescription,
    CalloutIcon,
} from '@posthog/quill'

import type { AiVisibilityBannerProps } from './AiVisibilityBanner'

const TONES = { error: 'destructive', info: 'info', warning: 'warning' } as const

export const QuillAiVisibilityBanner = ({
    type,
    action,
    onClose,
    className,
    children,
}: AiVisibilityBannerProps): JSX.Element => (
    <Callout tone={TONES[type]} className={className}>
        <CalloutIcon />
        <CalloutContent>
            <CalloutDescription>{children}</CalloutDescription>
        </CalloutContent>
        {action ? (
            <CalloutActions>
                <Button
                    variant="outline"
                    onClick={action.onClick}
                    loading={action.loading}
                    data-attr={action['data-attr']}
                >
                    {action.children}
                </Button>
            </CalloutActions>
        ) : null}
        {onClose ? <CalloutClose onClick={onClose} /> : null}
    </Callout>
)
