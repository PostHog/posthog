import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonSwitch } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { autoResolveConfigLogic } from './autoResolveConfigLogic'
import { AUTO_RESOLVE_MAX_DAYS, AUTO_RESOLVE_MIN_DAYS, isValidAutoResolveDays } from './autoResolveDays'

export function AutoResolveSettings(): JSX.Element {
    const { configLoading, configLoadFailed, configForm, configFormChanged, isConfigFormSubmitting } =
        useValues(autoResolveConfigLogic)

    if (configLoading) {
        return (
            <div className="space-y-4">
                <LemonSkeleton className="w-full h-10" />
                <LemonSkeleton className="w-full h-10" />
            </div>
        )
    }

    if (configLoadFailed) {
        return (
            <LemonBanner type="error">
                Couldn't load the auto-resolve settings. Refresh the page to try again.
            </LemonBanner>
        )
    }

    const days = isValidAutoResolveDays(configForm.days) ? configForm.days : null

    return (
        <Form
            logic={autoResolveConfigLogic}
            formKey="configForm"
            enableFormOnSubmit
            // The days input keeps min, max and step for its spinner. Without noValidate, the browser blocks the
            // submit with its own tooltip, so the form never shows its range message under the field.
            noValidate
            className="space-y-4 max-w-160"
        >
            <LemonField name="enabled">
                {({ value, onChange }) => (
                    <LemonSwitch
                        checked={value}
                        onChange={onChange}
                        label="Auto-resolve quiet issues"
                        bordered
                        data-attr="error-tracking-auto-resolve-toggle"
                    />
                )}
            </LemonField>

            {configForm.enabled ? (
                <>
                    <LemonField name="days" label="Resolve after">
                        {({ value, onChange }) => (
                            <div className="flex flex-wrap items-center gap-2">
                                <LemonInput
                                    type="number"
                                    min={AUTO_RESOLVE_MIN_DAYS}
                                    max={AUTO_RESOLVE_MAX_DAYS}
                                    step={1}
                                    value={value ?? undefined}
                                    onChange={(v) => onChange(v ?? null)}
                                    className="w-24"
                                    data-attr="error-tracking-auto-resolve-days"
                                />
                                <span>days without exceptions</span>
                            </div>
                        )}
                    </LemonField>

                    <LemonBanner type="info">
                        <ul className="list-disc pl-4 space-y-1">
                            <li>
                                {days !== null
                                    ? `An active issue resolves after about ${days} ${days === 1 ? 'day' : 'days'} with no exceptions and no changes.`
                                    : 'An active issue resolves after about that many days with no exceptions and no changes.'}{' '}
                                Reopening, assigning or editing an issue starts the count again. Suppressed issues never
                                resolve.
                            </li>
                            <li>
                                If the error happens again, the issue reopens and your reopened issue alerts fire. To
                                avoid this for errors that come back now and then, choose more days than the usual gap
                                between them.
                            </li>
                            <li>
                                The first run resolves every quiet issue at once. Alerts set up for resolved issues fire
                                for each one.
                            </li>
                        </ul>
                    </LemonBanner>
                </>
            ) : null}

            <div className="flex justify-start">
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    disabledReason={
                        errorTrackingEditAccessDisabledReason() ??
                        (!configFormChanged ? 'No changes to save' : undefined)
                    }
                    loading={isConfigFormSubmitting}
                    data-attr="error-tracking-auto-resolve-save"
                >
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}
