import { LemonTag } from '@posthog/lemon-ui'

import type { RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { RecipientLastSent } from './RecipientLastSent'
import { RecipientPersonsSummary } from './RecipientPersonsSummary'
import { NARROW_RECIPIENTS_TABLE_ONLY } from './recipientsTableLayout'

export function RecipientCell({ recipient }: { recipient: RecipientApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 min-w-0">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span translate="no" className="font-medium wrap-anywhere">
                    {recipient.email}
                </span>
                {recipient.suppression && (
                    <LemonTag type="danger" size="small">
                        Suppressed
                    </LemonTag>
                )}
            </div>
            <div className={`${NARROW_RECIPIENTS_TABLE_ONLY} flex flex-wrap gap-x-2 text-xs text-secondary`}>
                <RecipientPersonsSummary recipient={recipient} />
                <span>
                    <span>Last sent (30 days): </span>
                    <RecipientLastSent recipient={recipient} />
                </span>
            </div>
        </div>
    )
}
