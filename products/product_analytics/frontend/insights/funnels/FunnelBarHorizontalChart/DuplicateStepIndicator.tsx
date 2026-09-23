import { IconInfo } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function DuplicateStepIndicator(): JSX.Element {
    return (
        <Tooltip
            title={
                <>
                    <b>This is a repeated event in a sequence</b>
                    <p>
                        When an event is repeated across funnel steps, it is interpreted as a sequence. For example, a
                        three-step funnel consisting of pageview events is interpretted as first pageview, followed by
                        second pageview, followed by a third pageview.
                    </p>
                </>
            }
        >
            <IconInfo style={{ marginLeft: '0.375rem', fontSize: '1.25rem', color: 'var(--color-text-secondary)' }} />
        </Tooltip>
    )
}
