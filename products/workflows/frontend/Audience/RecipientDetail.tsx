import { BindLogic, useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { audienceSceneLogic } from './audienceSceneLogic'
import { RecipientDetailBody } from './RecipientDetailBody'
import { recipientDetailLogic } from './recipientDetailLogic'

export function RecipientDetail({ email }: { email: string }): JSX.Element {
    const { closeRecipient } = useActions(audienceSceneLogic)
    const backButtonRef = useRef<HTMLButtonElement>(null)

    useEffect(() => {
        backButtonRef.current?.focus()
    }, [])

    return (
        <BindLogic logic={recipientDetailLogic} props={{ email }}>
            <div className="flex flex-col gap-4 min-w-0 ph-no-capture" data-attr="audience-recipient-detail">
                <div>
                    <LemonButton
                        ref={backButtonRef}
                        type="tertiary"
                        size="small"
                        icon={<IconArrowLeft />}
                        onClick={closeRecipient}
                        data-attr="audience-recipient-back"
                    >
                        Back to recipients
                    </LemonButton>
                </div>
                <RecipientDetailBody />
            </div>
        </BindLogic>
    )
}
