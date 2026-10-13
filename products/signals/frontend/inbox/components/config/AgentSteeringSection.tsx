import { useActions, useValues } from 'kea'

import { IconCode, IconCompass, IconSearch } from '@posthog/icons'
import { LemonButton, LemonTabs, Link } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { InstructionsEditor } from 'scenes/settings/environment/InstructionsEditor'
import { urls } from 'scenes/urls'

import { SteeringRole, agentSteeringLogic } from '../../logics/agentSteeringLogic'
import { SettingsSection } from '../tabs/SettingsSection'

export function AgentSteeringSection(): JSX.Element {
    const { selectedRole, storedInstructions, instructions, instructionsDirty, steeringConfigLoading } =
        useValues(agentSteeringLogic)
    const { selectRole, setDraft, discardDraft, submitInstructions, loadSteeringConfig } =
        useActions(agentSteeringLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const roles: Record<SteeringRole, { title: string; description: string; placeholder: string }> = {
        scout: {
            title: 'Scout instructions',
            description:
                'Scouts explore product data and connected sources, find problems and opportunities, and create signals or reports.',
            placeholder: 'For example: Focus on onboarding failures. Exclude demo accounts from impact estimates.',
        },
        research: {
            title: 'Research instructions',
            description:
                'Research agents investigate signals, find root causes, assess impact and priority, and recommend what to do next.',
            placeholder: 'For example: Confirm whether the behavior is intentional before proposing a fix.',
        },
        implementation: {
            title: 'Implementation instructions',
            description:
                'Implementation agents turn reports into code changes, run checks, open pull requests, and address review feedback.',
            placeholder: 'For example: Keep changes focused. Add regression coverage and open draft pull requests.',
        },
    }
    const role = roles[selectedRole]

    return (
        <SettingsSection
            title="Steering"
            description={
                <>
                    Guide each agent's work in addition to your{' '}
                    <Link to={urls.settings('environment-task-agent-instructions', 'task-agent-project-instructions')}>
                        project instructions
                    </Link>
                    .
                </>
            }
        >
            <div>
                <LemonTabs
                    activeKey={selectedRole}
                    onChange={selectRole}
                    size="small"
                    tabs={[
                        {
                            key: 'research',
                            label: (
                                <span className="flex items-center gap-1">
                                    <IconSearch aria-hidden />
                                    Research
                                </span>
                            ),
                            'data-attr': 'signals-steering-research-tab',
                        },
                        {
                            key: 'implementation',
                            label: (
                                <span className="flex items-center gap-1">
                                    <IconCode aria-hidden />
                                    Implementation
                                </span>
                            ),
                            'data-attr': 'signals-steering-implementation-tab',
                        },
                        {
                            key: 'scout',
                            label: (
                                <span className="flex items-center gap-1">
                                    <IconCompass aria-hidden />
                                    Scouts
                                </span>
                            ),
                            'data-attr': 'signals-steering-scout-tab',
                        },
                    ]}
                />
                <div className="flex flex-col gap-2">
                    <h4 className="m-0 text-sm font-semibold">{role.title}</h4>
                    <p className="m-0 text-xs text-secondary">{role.description}</p>
                    <InstructionsEditor
                        stored={storedInstructions}
                        value={instructions}
                        dirty={instructionsDirty}
                        loading={steeringConfigLoading}
                        placeholder={role.placeholder}
                        onChange={(value) => setDraft(selectedRole, value)}
                        onSave={submitInstructions}
                        restrictionReason={restrictionReason}
                        dataAttr="signals-steering-instructions"
                        ariaLabel={role.title}
                    />
                    {storedInstructions === null && !steeringConfigLoading && (
                        <LemonButton onClick={loadSteeringConfig} size="small" data-attr="signals-steering-retry">
                            Retry
                        </LemonButton>
                    )}
                    {instructionsDirty && (
                        <LemonButton
                            type="tertiary"
                            size="small"
                            onClick={() => discardDraft(selectedRole)}
                            disabled={steeringConfigLoading}
                            data-attr="signals-steering-discard"
                        >
                            Discard changes
                        </LemonButton>
                    )}
                    {restrictionReason && (
                        <p className="m-0 text-xs text-secondary">Only project admins can edit these instructions.</p>
                    )}
                </div>
            </div>
        </SettingsSection>
    )
}
