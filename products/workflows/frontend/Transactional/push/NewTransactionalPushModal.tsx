import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { CyclotronJobInputIntegrationMulti } from 'lib/components/CyclotronJob/integrations/CyclotronJobInputIntegrationMulti'

import { CyclotronJobInputSchemaType } from '~/types'

import { newTransactionalPushLogic } from './newTransactionalPushLogic'

const CHANNELS_SCHEMA: CyclotronJobInputSchemaType = {
    key: 'channels',
    type: 'integration_multi',
    integration: 'firebase,apns',
    label: 'Push channels',
    required: true,
}

export function NewTransactionalPushModal(): JSX.Element {
    const { isOpen, name, draft, isCreating, createDisabledReason } = useValues(newTransactionalPushLogic)
    const { closeModal, setName, setDraft, create } = useActions(newTransactionalPushLogic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            title="New push notification"
            description="Send it from your server with one API call, to every device a person registered."
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeModal}
                        disabledReason={isCreating ? 'Creating' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={create}
                        loading={isCreating}
                        disabledReason={createDisabledReason ?? undefined}
                        data-attr="new-transactional-push-create"
                    >
                        Create
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <LemonLabel htmlFor="new-transactional-push-name">Name</LemonLabel>
                    <LemonInput
                        id="new-transactional-push-name"
                        value={name}
                        onChange={setName}
                        placeholder="Order shipped"
                        autoFocus
                        data-attr="new-transactional-push-name"
                    />
                </div>
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
                        htmlFor="new-transactional-push-title"
                        info="Use {{ variables.name }} for values you pass when you send it."
                    >
                        Title
                    </LemonLabel>
                    <LemonInput
                        id="new-transactional-push-title"
                        value={draft.title}
                        onChange={(title) => setDraft({ title })}
                        placeholder="Your order {{ variables.order_id }} has shipped"
                        data-attr="new-transactional-push-title"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel htmlFor="new-transactional-push-body">Message</LemonLabel>
                    <LemonTextArea
                        id="new-transactional-push-body"
                        value={draft.body}
                        onChange={(body) => setDraft({ body })}
                        placeholder="It arrives {{ variables.eta }}"
                        minRows={3}
                        data-attr="new-transactional-push-body"
                    />
                </div>
            </div>
        </LemonModal>
    )
}
