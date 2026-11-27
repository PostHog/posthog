import {
    Button,
    Callout,
    CalloutActions,
    CalloutClose,
    CalloutContent,
    CalloutDescription,
    CalloutIcon,
} from '@posthog/quill'

export interface AiVisibilityBannerAction {
    children: React.ReactNode
    onClick: () => void
    loading?: boolean
    'data-attr'?: string
}

export interface AiVisibilityBannerProps {
    type: 'error' | 'info' | 'warning' | 'success'
    action?: AiVisibilityBannerAction
    onClose?: () => void
    className?: string
    children: React.ReactNode
}

const TONES = { error: 'destructive', info: 'info', warning: 'warning', success: 'success' } as const

/** Carries its own quill scope, because the suggest dialogs are Lemon modals that portal outside the page's scope. */
export const AiVisibilityBanner = ({
    type,
    action,
    onClose,
    className,
    children,
}: AiVisibilityBannerProps): JSX.Element => (
    <Callout tone={TONES[type]} className={className} data-quill>
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
