import { LemonBanner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type {
    RecipientSuppressionApi,
    SuppressionSourceEnumApi,
} from 'products/messaging/frontend/generated/api.schemas'

const SUPPRESSION_SOURCE_LABELS: Record<SuppressionSourceEnumApi, string> = {
    BOUNCE: 'Repeated bounces',
    COMPLAINT: 'Marked as spam',
    MANUAL: 'Added manually',
}

export function RecipientSuppressionBanner({ suppression }: { suppression: RecipientSuppressionApi }): JSX.Element {
    return (
        <LemonBanner
            type="error"
            action={{
                children: 'Open suppression list',
                to: urls.audience('suppression'),
                'data-attr': 'audience-recipient-open-suppression-list',
            }}
        >
            <p className="m-0 font-semibold">This address is suppressed, so no email is sent to it.</p>
            <p className="m-0">
                {SUPPRESSION_SOURCE_LABELS[suppression.source]}
                {suppression.reason && `: ${suppression.reason}`}
                {suppression.suppressed_at && (
                    <>
                        {' '}
                        (since <TZLabel time={suppression.suppressed_at} />)
                    </>
                )}
            </p>
        </LemonBanner>
    )
}
