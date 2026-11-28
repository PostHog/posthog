import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { teamLogic } from 'scenes/teamLogic'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { AUTO_RESOLVE_MAX_DAYS, AUTO_RESOLVE_MIN_DAYS, autoResolveSettingsLogic } from './autoResolveSettingsLogic'
import { QuillAutoResolveSettings } from './QuillAutoResolveSettings'

export function AutoResolveSettings(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const projectId = currentTeamId ? String(currentTeamId) : ''
    const logic = autoResolveSettingsLogic({ projectId })
    const { settings, settingsLoadFailed, configForm, hasChanges, isConfigFormSubmitting } = useValues(logic)
    const { setConfigFormValue } = useActions(logic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const editDisabledReason = errorTrackingEditAccessDisabledReason()

    if (todayRailNav) {
        return <QuillAutoResolveSettings projectId={projectId} editDisabledReason={editDisabledReason} />
    }

    if (settingsLoadFailed) {
        return (
            <LemonBanner type="error">Couldn't load auto-resolve settings. Refresh the page to try again.</LemonBanner>
        )
    }

    if (!settings) {
        return <LemonSkeleton className="w-full h-10" />
    }

    const fieldDisabledReason = editDisabledReason ?? (isConfigFormSubmitting ? 'Saving settings' : undefined)

    return (
        <Form
            logic={autoResolveSettingsLogic}
            props={{ projectId }}
            formKey="configForm"
            enableFormOnSubmit
            noValidate
            className="space-y-4"
        >
            <LemonSwitch
                checked={configForm.enabled}
                onChange={(enabled) => setConfigFormValue('enabled', enabled)}
                label="Enable auto-resolve"
                aria-label="Enable auto-resolve"
                disabledReason={fieldDisabledReason}
                data-attr="error-tracking-auto-resolve-toggle"
            />
            {configForm.enabled && (
                <LemonField name="days" label="Days without exceptions">
                    {({ id, value, onChange }) => (
                        <LemonInput
                            id={id}
                            type="number"
                            min={AUTO_RESOLVE_MIN_DAYS}
                            max={AUTO_RESOLVE_MAX_DAYS}
                            step={1}
                            value={value ?? undefined}
                            onChange={(days) => onChange(days ?? null)}
                            className="w-32"
                            disabledReason={fieldDisabledReason}
                            data-attr="error-tracking-auto-resolve-days"
                        />
                    )}
                </LemonField>
            )}
            <LemonButton
                type="primary"
                htmlType="submit"
                disabledReason={editDisabledReason ?? (!hasChanges ? 'No changes to save' : undefined)}
                loading={isConfigFormSubmitting}
                data-attr="error-tracking-auto-resolve-save"
            >
                Save
            </LemonButton>
        </Form>
    )
}
