import { LemonTag } from '@posthog/lemon-ui'

export function SendCalendarTabLabel(): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            Calendar
            <LemonTag type="highlight" size="small">
                New
            </LemonTag>
        </span>
    )
}
