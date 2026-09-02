import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SlackDestinationPicker } from 'scenes/comments/SlackDestinationPicker'

import { AnyPropertyFilter } from '~/types'

import { AlertPreview } from './AlertPreview'
import { THROTTLE_OPTIONS, TRIGGER_OPTIONS, nativeAlertEditorLogic, splitChannel } from './nativeAlertEditorLogic'

export function NativeAlertEditor(): JSX.Element {
    const { isOpen, draft, preview, previewLoading, saving, deleting, saveDisabledReason } =
        useValues(nativeAlertEditorLogic)
    const {
        closeEditor,
        setDraft,
        setTriggerEnabled,
        addDestination,
        updateDestination,
        removeDestination,
        saveAlert,
        deleteAlert,
    } = useActions(nativeAlertEditorLogic)

    const firstChannel = splitChannel(draft.destinations[0]?.channel ?? null)
    const channelLabel = firstChannel?.channelName || null

    return (
        <LemonModal
            title={draft.id ? 'Edit alert' : 'New alert'}
            description={
                <span className="text-secondary">
                    Open a Slack thread when an issue matches, then keep the thread updated as the issue changes.
                </span>
            }
            isOpen={isOpen}
            onClose={closeEditor}
            width={1080}
            overlayClassName="pt-20"
            footer={
                <div className="flex justify-between w-full">
                    <div>
                        {draft.id && (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                onClick={deleteAlert}
                                loading={deleting}
                                disabledReason={saving ? 'Saving' : undefined}
                            >
                                Delete
                            </LemonButton>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={closeEditor}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={saveAlert}
                            loading={saving}
                            disabledReason={saveDisabledReason ?? (deleting ? 'Deleting' : undefined)}
                        >
                            {draft.id ? 'Save' : 'Create alert'}
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="grid gap-6 @container" style={{ gridTemplateColumns: 'minmax(0, 7fr) minmax(0, 6fr)' }}>
                <div className="flex flex-col gap-5">
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Name</LemonLabel>
                        <LemonInput
                            value={draft.name}
                            onChange={(name) => setDraft({ name })}
                            placeholder="Production errors"
                            data-attr="error-tracking-alert-name"
                        />
                    </div>

                    <div className="flex flex-col gap-2">
                        <LemonLabel>Open a thread when</LemonLabel>
                        <div className="flex flex-col gap-1.5">
                            {TRIGGER_OPTIONS.map((option) => (
                                <LemonCheckbox
                                    key={option.value}
                                    checked={draft.triggers.includes(option.value)}
                                    onChange={(checked) => setTriggerEnabled(option.value, checked)}
                                    label={
                                        <span>
                                            <span className="font-medium">{option.label}</span>
                                            <span className="text-secondary text-xs ml-2">{option.description}</span>
                                        </span>
                                    }
                                />
                            ))}
                        </div>
                    </div>

                    <div className="flex flex-col gap-1">
                        <LemonLabel info="Filters are checked against the exception that triggers the thread. Later updates to the issue are always posted into an open thread.">
                            Only if the exception matches
                        </LemonLabel>
                        <PropertyFilters
                            editable
                            propertyFilters={draft.properties}
                            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                            onChange={(properties: AnyPropertyFilter[]) => setDraft({ properties })}
                            pageKey="error-tracking-native-alert"
                            buttonSize="small"
                            hasRowOperator={false}
                            disablePopover
                        />
                    </div>

                    <div className="flex flex-col gap-2">
                        <LemonLabel>Deliver to</LemonLabel>
                        {draft.destinations.map((destination, index) => (
                            <div key={index} className="flex items-start gap-2 p-3 border rounded">
                                <SlackDestinationPicker
                                    className="flex-1"
                                    integrationId={destination.integrationId}
                                    channel={destination.channel}
                                    onIntegrationChange={(integrationId) =>
                                        updateDestination(index, { integrationId, channel: null })
                                    }
                                    onChannelChange={(channel) => updateDestination(index, { channel })}
                                />
                                {draft.destinations.length > 1 && (
                                    <LemonButton
                                        icon={<IconTrash />}
                                        size="small"
                                        onClick={() => removeDestination(index)}
                                        tooltip="Remove this channel"
                                    />
                                )}
                            </div>
                        ))}
                        <div>
                            <LemonButton icon={<IconPlus />} size="small" type="secondary" onClick={addDestination}>
                                Add another channel
                            </LemonButton>
                        </div>
                    </div>

                    <div className="flex flex-col gap-1">
                        <LemonLabel info="Limits how often the same issue can open a new thread in this alert's channels. Replies into an open thread are never limited.">
                            Open a thread per issue
                        </LemonLabel>
                        <LemonSelect
                            value={draft.throttleSeconds}
                            onChange={(throttleSeconds) => setDraft({ throttleSeconds })}
                            options={THROTTLE_OPTIONS}
                            size="small"
                        />
                    </div>
                </div>

                <AlertPreview preview={preview} loading={previewLoading} channelLabel={channelLabel} />
            </div>
        </LemonModal>
    )
}
