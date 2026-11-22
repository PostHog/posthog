import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { Button, Input, Item, ItemActions, ItemContent, ItemDescription, Skeleton, Text } from '@posthog/quill'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { QuillConfigurationFormField } from '../QuillConfigurationFormField'
import { QuillConfigurationSubsection } from '../QuillConfigurationSubsection'
import { RecentSpikes } from './RecentSpikes'
import { spikeDetectionConfigLogic } from './spikeDetectionConfigLogic'

const SPIKE_DETECTION_FIELDS = [
    {
        name: 'snooze_duration_minutes',
        label: 'Snooze duration (minutes)',
        description: 'Time to wait before alerting again for the same issue after a spike is detected.',
        placeholder: '10',
        dataAttr: 'spike-detection-snooze-duration',
    },
    {
        name: 'multiplier',
        label: 'Multiplier',
        description:
            'The factor by which the current exception count must exceed the baseline to be considered a spike.',
        placeholder: '10',
        dataAttr: 'spike-detection-multiplier',
    },
    {
        name: 'threshold',
        label: 'Minimum threshold',
        description: 'The minimum number of exceptions required in a 5-minute window before a spike can be detected.',
        placeholder: '500',
        dataAttr: 'spike-detection-threshold',
    },
]

export function QuillSpikeDetectionSettings({ onConfigureAlerts }: { onConfigureAlerts: () => void }): JSX.Element {
    const { configLoading, configFormChanged, isConfigFormSubmitting, hasSpikeAlerts } =
        useValues(spikeDetectionConfigLogic)

    if (configLoading) {
        return (
            <div className="flex flex-col gap-4">
                <Skeleton className="w-full h-10" />
                <Skeleton className="w-full h-10" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-8">
            <Form
                logic={spikeDetectionConfigLogic}
                formKey="configForm"
                enableFormOnSubmit
                className="@container flex flex-col gap-4"
            >
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Spike detection is in early stage. We may make changes to the defaults or replace these
                            settings as we iterate. We'd love your feedback!
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="outline" id="spike-detection-feedback-button">
                            Send feedback
                        </Button>
                    </ItemActions>
                </Item>

                {!hasSpikeAlerts && (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                You don't have any alerts configured for spike events. Set up notifications to get
                                alerted when issues spike.
                            </ItemDescription>
                        </ItemContent>
                        <ItemActions>
                            <Button variant="outline" onClick={onConfigureAlerts}>
                                Configure alerts
                            </Button>
                        </ItemActions>
                    </Item>
                )}

                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Configure spike detection settings for error tracking alerts. When an issue receives significantly
                    more exceptions than its baseline, a spike alert will be triggered.
                </Text>

                <div className="grid grid-cols-1 gap-4 @xl:grid-cols-3">
                    {SPIKE_DETECTION_FIELDS.map((field) => (
                        <QuillConfigurationFormField
                            key={field.name}
                            name={field.name}
                            label={field.label}
                            description={field.description}
                        >
                            {({ id, value, onChange, invalid }) => (
                                <Input
                                    id={id}
                                    type="number"
                                    min={1}
                                    placeholder={field.placeholder}
                                    value={value ?? ''}
                                    onChange={(event) =>
                                        onChange(event.target.value === '' ? undefined : Number(event.target.value))
                                    }
                                    aria-invalid={invalid || undefined}
                                    data-attr={field.dataAttr}
                                />
                            )}
                        </QuillConfigurationFormField>
                    ))}
                </div>

                <div className="flex justify-end">
                    <Button
                        variant="primary"
                        type="submit"
                        disabledReason={
                            errorTrackingEditAccessDisabledReason() ??
                            (!configFormChanged ? 'No changes to save' : undefined)
                        }
                        loading={isConfigFormSubmitting}
                    >
                        Save
                    </Button>
                </div>
            </Form>

            <QuillConfigurationSubsection title="Recent spike events">
                <RecentSpikes />
            </QuillConfigurationSubsection>
        </div>
    )
}
