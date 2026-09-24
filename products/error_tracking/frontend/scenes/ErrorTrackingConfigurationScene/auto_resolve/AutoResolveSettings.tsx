import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonSwitch } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { MAX_AUTO_RESOLVE_DAYS, MIN_AUTO_RESOLVE_DAYS, autoResolveConfigLogic } from './autoResolveConfigLogic'

export function AutoResolveSettings(): JSX.Element {
    const { configLoading, configForm, configFormChanged, isConfigFormSubmitting } = useValues(autoResolveConfigLogic)

    if (configLoading) {
        return <LemonSkeleton className="w-full h-10" />
    }

    return (
        <Form logic={autoResolveConfigLogic} formKey="configForm" enableFormOnSubmit className="space-y-4">
            <p className="text-muted-foreground">
                Resolve active issues that stop receiving exceptions. If the error happens again, the issue reopens on
                its own.
            </p>

            <LemonField name="enabled">
                {({ value, onChange }) => (
                    <LemonSwitch
                        checked={value}
                        onChange={onChange}
                        label="Auto-resolve inactive issues"
                        bordered
                        data-attr="error-tracking-auto-resolve-toggle"
                    />
                )}
            </LemonField>

            <LemonField
                name="days"
                label="Days without a new exception"
                info="Checked once a day. Suppressed issues are never auto-resolved."
                className="max-w-60"
            >
                <LemonInput
                    type="number"
                    min={MIN_AUTO_RESOLVE_DAYS}
                    max={MAX_AUTO_RESOLVE_DAYS}
                    step={1}
                    fullWidth
                    disabledReason={!configForm.enabled ? 'Turn on auto-resolve first' : undefined}
                    data-attr="error-tracking-auto-resolve-days"
                />
            </LemonField>

            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    disabledReason={
                        errorTrackingEditAccessDisabledReason() ??
                        (!configFormChanged ? 'No changes to save' : undefined)
                    }
                    loading={isConfigFormSubmitting}
                >
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}
