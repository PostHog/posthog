import { useValues } from 'kea'

import { AudienceRecipients } from './AudienceRecipients'
import { audienceSceneLogic } from './audienceSceneLogic'
import { recipientsLogic } from './recipientsLogic'
import { AudienceSetup } from './setup/AudienceSetup'

export function AudienceRecipientsTab(): JSX.Element {
    const { setupPageOpen } = useValues(audienceSceneLogic)
    const { showsSetup } = useValues(recipientsLogic)

    return setupPageOpen || showsSetup ? <AudienceSetup /> : <AudienceRecipients />
}
