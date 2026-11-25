import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonSwitch,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import {
    MAX_SLACK_SCOUT_CHANNELS,
    SLACK_SCOUT_SCHEDULE_OPTIONS,
    slackChannelScoutLogic,
} from '../../logics/slackChannelScoutLogic'

export function SlackChannelScoutModal(): JSX.Element {
    const formId = useId()
    const {
        isSlackScoutModalOpen,
        isSlackScoutSubmitting,
        slackScoutChanged,
        channelSources,
        channelOptions,
        unsyncedChannelCount,
    } = useValues(slackChannelScoutLogic)
    const { closeSlackScoutModal, setSlackScoutValue } = useActions(slackChannelScoutLogic)

    const handleClose = (): void => {
        if (!isSlackScoutSubmitting) {
            closeSlackScoutModal()
        }
    }

    return (
        <LemonModal
            isOpen={isSlackScoutModalOpen}
            onClose={handleClose}
            title="New Slack channel scout"
            description="The scout reads new messages in the channels you pick and files a report when people raise a problem or request worth acting on. It skips a run when the channels have no new messages."
            width={560}
            hasUnsavedInput={slackScoutChanged}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={handleClose}
                        disabledReason={isSlackScoutSubmitting ? 'Creating' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        form={formId}
                        htmlType="submit"
                        loading={isSlackScoutSubmitting}
                        data-attr="signal-slack-scout-create"
                    >
                        Create scout
                    </LemonButton>
                </>
            }
        >
            <Form logic={slackChannelScoutLogic} formKey="slackScout" id={formId} enableFormOnSubmit>
                <div className="flex flex-col gap-3">
                    <LemonField name="display_name" label="Name">
                        <LemonInput placeholder="Support channels" data-attr="signal-slack-scout-name" />
                    </LemonField>
                    {(channelSources?.length ?? 0) > 1 && (
                        <LemonField name="source_id" label="Slack source">
                            {({ value, onChange }) => (
                                <LemonSelect
                                    value={value}
                                    onChange={(sourceId) => {
                                        onChange(sourceId)
                                        setSlackScoutValue('channel_ids', [])
                                    }}
                                    options={(channelSources ?? []).map((source, index) => ({
                                        value: source.id,
                                        label: `Slack source ${index + 1}`,
                                    }))}
                                    fullWidth
                                />
                            )}
                        </LemonField>
                    )}
                    <LemonField
                        name="channel_ids"
                        label="Channels"
                        help={
                            unsyncedChannelCount > 0
                                ? `${unsyncedChannelCount} more ${unsyncedChannelCount === 1 ? 'channel appears' : 'channels appear'} here after the first sync.`
                                : `Up to ${MAX_SLACK_SCOUT_CHANNELS} channels.`
                        }
                    >
                        {({ value, onChange }) => (
                            <LemonInputSelect
                                mode="multiple"
                                value={value}
                                onChange={onChange}
                                options={channelOptions}
                                placeholder="Pick channels"
                                data-attr="signal-slack-scout-channels"
                            />
                        )}
                    </LemonField>
                    <LemonField
                        name="steer"
                        label="What to look for"
                        help="Leave it empty to look for bug reports, repeated requests, and complaints."
                        showOptional
                    >
                        <LemonTextArea
                            minRows={3}
                            maxRows={8}
                            placeholder="Questions about billing and pricing that come up more than once."
                            data-attr="signal-slack-scout-steer"
                        />
                    </LemonField>
                    <LemonField name="run_cron_schedule" label="Schedule">
                        {({ value, onChange }) => (
                            <LemonSelect
                                value={value}
                                onChange={onChange}
                                options={SLACK_SCOUT_SCHEDULE_OPTIONS}
                                fullWidth
                                data-attr="signal-slack-scout-schedule"
                            />
                        )}
                    </LemonField>
                    <LemonField
                        name="emit"
                        help="The scout runs and logs what it finds, but files nothing in the inbox."
                    >
                        {({ value, onChange }) => (
                            <LemonSwitch
                                checked={!value}
                                onChange={(dryRun) => onChange(!dryRun)}
                                label="Dry run"
                                bordered
                                fullWidth
                                data-attr="signal-slack-scout-dry-run"
                            />
                        )}
                    </LemonField>
                </div>
            </Form>
        </LemonModal>
    )
}
