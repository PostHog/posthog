import { Button, Input, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Text } from '@posthog/quill'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { QuillConfigurationFormField } from '../QuillConfigurationFormField'
import { BUCKET_OPTIONS } from './rateLimitConfigLogic'

export function QuillRateLimitConfigFields({
    valueFieldName,
    bucketFieldName,
    valueDataAttr,
    bucketDataAttr,
    formChanged,
    formSubmitting,
}: {
    valueFieldName: string
    bucketFieldName: string
    valueDataAttr: string
    bucketDataAttr: string
    formChanged: boolean
    formSubmitting: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <QuillConfigurationFormField name={valueFieldName} label="Maximum exceptions">
                {({ id, value, onChange, invalid }) => (
                    <Input
                        id={id}
                        type="number"
                        min={1}
                        value={value ?? ''}
                        onChange={(event) => onChange(event.target.value === '' ? null : Number(event.target.value))}
                        placeholder="Unlimited"
                        aria-invalid={invalid || undefined}
                        data-attr={valueDataAttr}
                    />
                )}
            </QuillConfigurationFormField>

            <QuillConfigurationFormField name={bucketFieldName} label="Per">
                {({ id, value, onChange }) => (
                    <Select value={value} onValueChange={(next) => onChange(next as number)}>
                        <SelectTrigger id={id} className="w-full" data-attr={bucketDataAttr}>
                            <SelectValue>
                                {(minutes: number) =>
                                    BUCKET_OPTIONS.find((option) => option.minutes === minutes)?.label
                                }
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {BUCKET_OPTIONS.map((option) => (
                                <SelectItem key={option.minutes} value={option.minutes}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                )}
            </QuillConfigurationFormField>

            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Leave the value empty for no limit.
            </Text>

            <div>
                <Button
                    variant="primary"
                    type="submit"
                    disabledReason={
                        errorTrackingEditAccessDisabledReason() ?? (!formChanged ? 'No changes to save' : undefined)
                    }
                    loading={formSubmitting}
                >
                    Save
                </Button>
            </div>
        </div>
    )
}
