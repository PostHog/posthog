import { LemonBanner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { QuillAiVisibilityBanner } from './QuillAiVisibilityBanner'

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

/** A banner in AI visibility: a quill callout under the new navigation, a Lemon banner otherwise. */
export const AiVisibilityBanner = (props: AiVisibilityBannerProps): JSX.Element => {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillAiVisibilityBanner {...props} />
    }
    const { type, action, onClose, className, children } = props
    return (
        <LemonBanner type={type} action={action} onClose={onClose} className={className}>
            {children}
        </LemonBanner>
    )
}
