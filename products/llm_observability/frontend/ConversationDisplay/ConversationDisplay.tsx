import { EventType } from '~/types'

import { ConversationMessagesDisplay } from './ConversationMessagesDisplay'
import { MetadataHeader } from './MetadataHeader'

export function ConversationDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    return (
        <>
            <header className="mb-2">
                <MetadataHeader eventProperties={eventProperties} />
            </header>
            <ConversationMessagesDisplay eventProperties={eventProperties} />
        </>
    )
}
