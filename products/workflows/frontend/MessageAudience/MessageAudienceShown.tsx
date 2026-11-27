import { useEffect } from 'react'

import { MessageAudienceDestination, captureMessageAudienceShown } from './messageAudience'

export interface MessageAudienceShownProps {
    source: string
    destination: MessageAudienceDestination
}

export function MessageAudienceShown({ source, destination }: MessageAudienceShownProps): null {
    useEffect(() => captureMessageAudienceShown(source, destination), [source, destination])
    return null
}
