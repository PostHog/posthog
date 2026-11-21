import { useActions, useValues } from 'kea'

import { LemonInput, LemonLabel, LemonTextArea } from '@posthog/lemon-ui'

import { CyclotronJobInputIntegrationMulti } from 'lib/components/CyclotronJob/integrations/CyclotronJobInputIntegrationMulti'

import { CyclotronJobInputSchemaType } from '~/types'

import { transactionalPushLogic } from './transactionalPushLogic'
import { TransactionalPushPreview } from './TransactionalPushPreview'
import { TransactionalPushTestSend } from './TransactionalPushTestSend'

const CHANNELS_SCHEMA: CyclotronJobInputSchemaType = {
    key: 'channels',
    type: 'integration_multi',
    integration: 'firebase,apns',
    label: 'Push channels',
    required: true,
}

export function TransactionalPushEditor({ id }: { id: string }): JSX.Element {
    const { draft, dataError, variables, transactionalHogFlowId } = useValues(transactionalPushLogic({ id }))
    const { setDraft } = useActions(transactionalPushLogic({ id }))

    return (
        <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-2">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <LemonLabel info="Each person gets the notification on every device they registered with these apps.">
                        Send through
                    </LemonLabel>
                    <CyclotronJobInputIntegrationMulti
                        schema={CHANNELS_SCHEMA}
                        value={draft.channels}
                        onChange={(channels) => setDraft({ channels })}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel
                        htmlFor="transactional-push-title"
                        info="Use {{ variables.name }} for values you pass in message_data."
                    >
                        Title
                    </LemonLabel>
                    <LemonInput
                        id="transactional-push-title"
                        value={draft.title}
                        onChange={(title) => setDraft({ title })}
                        placeholder="Your order {{ variables.order_id }} has shipped"
                        data-attr="transactional-push-title"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel htmlFor="transactional-push-body">Message</LemonLabel>
                    <LemonTextArea
                        id="transactional-push-body"
                        value={draft.body}
                        onChange={(body) => setDraft({ body })}
                        placeholder="It arrives {{ variables.eta }}"
                        minRows={3}
                        data-attr="transactional-push-body"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel
                        htmlFor="transactional-push-link"
                        info='Where a tap takes the person. Your app gets it as the "link" key in the custom data.'
                        showOptional
                    >
                        Link
                    </LemonLabel>
                    <LemonInput
                        id="transactional-push-link"
                        value={draft.link}
                        onChange={(link) => setDraft({ link })}
                        placeholder="myapp://orders/{{ variables.order_id }}"
                        data-attr="transactional-push-link"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel htmlFor="transactional-push-image" showOptional>
                        Image URL
                    </LemonLabel>
                    <LemonInput
                        id="transactional-push-image"
                        value={draft.image}
                        onChange={(image) => setDraft({ image })}
                        placeholder="https://example.com/image.png"
                        data-attr="transactional-push-image"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel
                        htmlFor="transactional-push-data"
                        info="Keys and string values your app's code reads when the notification arrives."
                        showOptional
                    >
                        Custom data
                    </LemonLabel>
                    <LemonTextArea
                        id="transactional-push-data"
                        className="font-mono"
                        value={draft.data}
                        onChange={(data) => setDraft({ data })}
                        placeholder='{"order_id": "{{ variables.order_id }}"}'
                        minRows={2}
                        data-attr="transactional-push-data"
                    />
                    {dataError ? <span className="text-xs text-danger">{dataError}</span> : null}
                </div>
                {variables.length ? (
                    <p className="m-0 text-xs text-secondary">
                        Pass {variables.map((name) => `"${name}"`).join(', ')} in message_data when you send it.
                    </p>
                ) : null}
            </div>
            <div className="flex flex-col gap-3">
                <TransactionalPushPreview title={draft.title} body={draft.body} />
                {transactionalHogFlowId ? <TransactionalPushTestSend id={id} /> : null}
            </div>
        </div>
    )
}
