import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { AUTONOMY_PRIORITY_OPTIONS } from '../../utils/autonomyPriorityOptions'
import { AutonomySettingGroup } from '../config/AutonomySettingGroup'
import { AutonomySettingRow } from '../config/AutonomySettingRow'

export function InboxSetupImplementation(): JSX.Element {
    const { draft, saving } = useValues(inboxSetupLogic)
    const { patchDraft } = useActions(inboxSetupLogic)
    return (
        <div className="border-t border-primary pt-4">
            <AutonomySettingGroup title="Automatic implementation">
                <AutonomySettingRow
                    title="Automatically fix what agents find"
                    description="Agents find and investigate problems by default. Turn this on to also get fixes as pull requests. You review and merge."
                    control={
                        <LemonSwitch
                            checked={draft.automatic_implementation}
                            onChange={(automatic_implementation) => patchDraft({ automatic_implementation })}
                            disabled={saving}
                            aria-label="Automatically fix what agents find"
                            data-attr="inbox-setup-automatic-implementation"
                        />
                    }
                >
                    {draft.automatic_implementation && (
                        <AutonomySettingRow
                            title="Priority threshold"
                            description="Agents open PRs for reports at this priority or higher."
                            control={
                                <LemonSegmentedButton
                                    size="small"
                                    fullWidth
                                    value={draft.implementation_priority}
                                    options={AUTONOMY_PRIORITY_OPTIONS}
                                    onChange={(implementation_priority) => patchDraft({ implementation_priority })}
                                    disabledReason={saving ? 'Saving setup' : undefined}
                                />
                            }
                        />
                    )}
                </AutonomySettingRow>
            </AutonomySettingGroup>
        </div>
    )
}
