import { useActions, useValues } from 'kea'

import { LemonInput, LemonLabel, LemonTextArea } from '@posthog/lemon-ui'

import { CyclotronJobInputIntegrationMulti } from 'lib/components/CyclotronJob/integrations/CyclotronJobInputIntegrationMulti'

import { CyclotronJobInputSchemaType } from '~/types'

import { BroadcastPushPreview } from '../BroadcastPushPreview'
import { PUSH_INTEGRATION_KINDS, broadcastWizardLogic } from '../broadcastWizardLogic'

const CHANNELS_SCHEMA: CyclotronJobInputSchemaType = {
    key: 'channels',
    type: 'integration_multi',
    integration: PUSH_INTEGRATION_KINDS.join(','),
    label: 'Push channels',
    required: true,
}

export function BroadcastPushComposer(): JSX.Element {
    const { push, stepValidationErrors, templatingErrors } = useValues(broadcastWizardLogic)
    const { setPush } = useActions(broadcastWizardLogic)
    const templatingMessages: (string | undefined)[] = Object.values(templatingErrors)
    const errors = stepValidationErrors.content.filter((error) => !templatingMessages.includes(error))
    const channelsError = errors.find((error) => error.includes('channel'))
    const titleError = errors.find((error) => error.includes('title')) ?? templatingErrors.title
    const messageError = templatingErrors.message

    return (
        <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-2">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <LemonLabel info="Each person gets the notification on the devices they registered with these apps.">
                        Send through
                    </LemonLabel>
                    <CyclotronJobInputIntegrationMulti
                        schema={CHANNELS_SCHEMA}
                        value={push.channels}
                        onChange={(channels) => setPush({ ...push, channels })}
                    />
                    {channelsError ? <span className="text-xs text-danger">{channelsError}</span> : null}
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel htmlFor="broadcast-push-title">Title</LemonLabel>
                    <LemonInput
                        id="broadcast-push-title"
                        value={push.title}
                        onChange={(title) => setPush({ ...push, title })}
                        placeholder="Your order has shipped"
                        status={titleError ? 'danger' : undefined}
                        data-attr="broadcast-push-title"
                    />
                    {titleError ? <span className="text-xs text-danger">{titleError}</span> : null}
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel
                        htmlFor="broadcast-push-body"
                        info="Supports variables such as {{ person.properties.name }}."
                    >
                        Message
                    </LemonLabel>
                    <LemonTextArea
                        id="broadcast-push-body"
                        value={push.body}
                        onChange={(body) => setPush({ ...push, body })}
                        placeholder="Optional"
                        minRows={3}
                        data-attr="broadcast-push-body"
                    />
                    {messageError ? <span className="text-xs text-danger">{messageError}</span> : null}
                </div>
            </div>
            <BroadcastPushPreview />
        </div>
    )
}
