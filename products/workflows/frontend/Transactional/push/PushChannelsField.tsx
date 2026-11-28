import { LemonLabel } from '@posthog/lemon-ui'

import { CyclotronJobInputIntegrationMulti } from 'lib/components/CyclotronJob/integrations/CyclotronJobInputIntegrationMulti'

import { CyclotronJobInputSchemaType } from '~/types'

import { PushChannelsSetupWarning } from './PushChannelsSetupWarning'

const CHANNELS_SCHEMA: CyclotronJobInputSchemaType = {
    key: 'channels',
    type: 'integration_multi',
    integration: 'firebase,apns',
    label: 'Push channels',
    required: true,
}

export function PushChannelsField({
    channels,
    onChange,
}: {
    channels: number[]
    onChange: (channels: number[]) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <LemonLabel info="Each person gets the notification on every device they registered with these apps.">
                Send through
            </LemonLabel>
            <CyclotronJobInputIntegrationMulti schema={CHANNELS_SCHEMA} value={channels} onChange={onChange} />
            <PushChannelsSetupWarning channels={channels} />
        </div>
    )
}
