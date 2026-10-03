import { BindLogic } from 'kea'

import { recipientTimelineLogic } from './recipientTimelineLogic'
import { RecipientTimelineTable } from './RecipientTimelineTable'

export function RecipientTimeline({ email }: { email: string }): JSX.Element {
    return (
        <BindLogic logic={recipientTimelineLogic} props={{ email }}>
            <RecipientTimelineTable />
        </BindLogic>
    )
}
