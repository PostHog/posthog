import { TZLabel } from 'lib/components/TZLabel'

import type { RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

export function RecipientLastSent({ recipient }: { recipient: RecipientApi }): JSX.Element {
    return recipient.last_sent_at ? (
        <TZLabel time={recipient.last_sent_at} />
    ) : (
        <span className="text-xs text-secondary">None</span>
    )
}
