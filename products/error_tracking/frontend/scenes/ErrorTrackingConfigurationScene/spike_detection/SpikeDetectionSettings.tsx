import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { spikeDetectionConfigLogic } from './spikeDetectionConfigLogic'

export function SpikeDetectionSettings(): JSX.Element {
    const { configLoading, configFormChanged, isConfigFormSubmitting } = useValues(spikeDetectionConfigLogic)

    if (configLoading) {
        return (
            <div className="space-y-4">
                <LemonSkeleton className="w-full h-10" />
                <LemonSkeleton className="w-full h-10" />
                <LemonSkeleton className="w-full h-10" />
            </div>
        )
    }

    return (
        <Form logic={spikeDetectionConfigLogic} formKey="configForm" enableFormOnSubmit className="space-y-4">
            <p className="text-muted-foreground">
                Configure spike detection settings for error tracking alerts. When an issue receives significantly more
                exceptions than its baseline, a spike alert will be triggered.
            </p>

            <LemonField name="snooze_duration_minutes" label="Snooze duration (minutes)">
                <LemonInput
                    type="number"
                    min={1}
                    placeholder="10"
                    fullWidth
                    data-attr="spike-detection-snooze-duration"
                />
            </LemonField>

            <p className="text-xs text-muted-foreground -mt-2">
                After a spike alert fires for an issue, you won't receive another alert for the same issue until this
                duration has passed.
            </p>

            <LemonField name="multiplier" label="Multiplier">
                <LemonInput type="number" min={1} placeholder="10" fullWidth data-attr="spike-detection-multiplier" />
            </LemonField>

            <p className="text-xs text-muted-foreground -mt-2">
                The number of times the current exception count must exceed the baseline to trigger a spike alert. For
                example, a multiplier of 10 means you need 10x more exceptions than normal.
            </p>

            <LemonField name="threshold" label="Minimum threshold">
                <LemonInput type="number" min={1} placeholder="500" fullWidth data-attr="spike-detection-threshold" />
            </LemonField>

            <p className="text-xs text-muted-foreground -mt-2">
                The minimum number of exceptions in a time window required before a spike alert can fire. This prevents
                alerts from firing for issues with very low traffic.
            </p>

            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    disabledReason={!configFormChanged ? 'No changes to save' : undefined}
                    loading={isConfigFormSubmitting}
                >
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}
