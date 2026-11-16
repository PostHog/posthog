import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { SendFromCodeSurface } from './firstCodeSendLogic'
import { SendFromCodeSnippet } from './SendFromCodeSnippet'
import { sendingDomainLogic } from './sendingDomainLogic'

export function ProjectSenderSnippet({ surface }: { surface: SendFromCodeSurface }): JSX.Element {
    const { sendingDomain, integrationsFailed } = useValues(sendingDomainLogic)
    if (!sendingDomain && !integrationsFailed) {
        return <LemonSkeleton className="h-60" />
    }
    return (
        <SendFromCodeSnippet
            from={sendingDomain?.status === 'verified' ? sendingDomain.from : null}
            surface={surface}
        />
    )
}
