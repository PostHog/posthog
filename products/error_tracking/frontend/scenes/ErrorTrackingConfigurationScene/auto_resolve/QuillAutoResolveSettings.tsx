import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import { Button, Field, FieldLabel, Input, Item, ItemContent, ItemDescription, Skeleton, Switch } from '@posthog/quill'

import { QuillConfigurationFormField } from '../QuillConfigurationFormField'
import { AUTO_RESOLVE_MAX_DAYS, AUTO_RESOLVE_MIN_DAYS, autoResolveSettingsLogic } from './autoResolveSettingsLogic'

export function QuillAutoResolveSettings({
    projectId,
    editDisabledReason,
}: {
    projectId: string
    editDisabledReason: string | null
}): JSX.Element {
    const logic = autoResolveSettingsLogic({ projectId })
    const { settings, settingsLoadFailed, configForm, hasChanges, isConfigFormSubmitting } = useValues(logic)
    const { setConfigFormValue } = useActions(logic)
    const switchId = useId()

    if (settingsLoadFailed) {
        return (
            <Item tone="destructive" size="sm">
                <ItemContent>
                    <ItemDescription>
                        Couldn't load auto-resolve settings. Refresh the page to try again.
                    </ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    if (!settings) {
        return <Skeleton className="w-full h-10" />
    }

    const fieldDisabledReason = editDisabledReason ?? (isConfigFormSubmitting ? 'Saving settings' : undefined)

    return (
        <Form
            logic={autoResolveSettingsLogic}
            props={{ projectId }}
            formKey="configForm"
            enableFormOnSubmit
            noValidate
            className="flex flex-col items-start gap-4"
        >
            <Field orientation="horizontal" className="w-fit">
                <Switch
                    id={switchId}
                    checked={configForm.enabled}
                    onCheckedChange={(enabled) => setConfigFormValue('enabled', enabled)}
                    disabledReason={fieldDisabledReason}
                    data-attr="error-tracking-auto-resolve-toggle"
                />
                <FieldLabel htmlFor={switchId}>Enable auto-resolve</FieldLabel>
            </Field>
            {configForm.enabled && (
                <QuillConfigurationFormField name="days" label="Days without exceptions">
                    {({ id, value, onChange, invalid }) => (
                        <Input
                            id={id}
                            type="number"
                            min={AUTO_RESOLVE_MIN_DAYS}
                            max={AUTO_RESOLVE_MAX_DAYS}
                            step={1}
                            value={value ?? ''}
                            onChange={({ currentTarget }) =>
                                onChange(currentTarget.value === '' ? null : currentTarget.valueAsNumber)
                            }
                            className="max-w-32"
                            disabled={!!fieldDisabledReason}
                            aria-invalid={invalid || undefined}
                            data-attr="error-tracking-auto-resolve-days"
                        />
                    )}
                </QuillConfigurationFormField>
            )}
            <Button
                variant="primary"
                type="submit"
                disabledReason={editDisabledReason ?? (!hasChanges ? 'No changes to save' : undefined)}
                loading={isConfigFormSubmitting}
                data-attr="error-tracking-auto-resolve-save"
            >
                Save
            </Button>
        </Form>
    )
}
