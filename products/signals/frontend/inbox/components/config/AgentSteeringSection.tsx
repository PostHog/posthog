import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCode, IconCompass, IconSearch } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonTabs, Link } from '@posthog/lemon-ui'

import { useAnchor } from 'lib/hooks/useAnchor'
import { InstructionsEditor } from 'scenes/settings/environment/InstructionsEditor'
import { urls } from 'scenes/urls'

import { SteeringRole, agentSteeringLogic } from '../../logics/agentSteeringLogic'
import { SettingsSection } from '../tabs/SettingsSection'

export function AgentSteeringSection(): JSX.Element {
    const { location } = useValues(router)
    useAnchor(location.hash === '#steering' ? location.hash : '')
    const { selectedRole, storedInstructions, instructions, instructionsDirty, steeringConfigLoading, dirtyRoles } =
        useValues(agentSteeringLogic)
    const { selectRole, setDraft, discardDraft, submitInstructions, loadSteeringConfig } =
        useActions(agentSteeringLogic)
    const roles: Record<SteeringRole, { title: string; description: string; placeholder: string }> = {
        scout: {
            title: 'Scout instructions',
            description:
                'Scouts explore product data and connected sources, find problems and opportunities, and create signals or reports.',
            placeholder: 'For example: Focus on onboarding failures. Exclude demo accounts from impact estimates.',
        },
        research: {
            title: 'Research instructions',
            description: 'Investigate signals, assess priority, and write reports.',
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
            id="steering"
            title="Steering"
            description={
                <>
                    Guide each agent's work in addition to your{' '}
                    <Link
                        to={urls.settings('environment-task-agent-instructions', 'task-agent-project-instructions')}
                        data-attr="signals-steering-project-instructions"
                    >
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
                                    <span>Research</span>
                                    <LemonBadge
                                        size="xsmall"
                                        visible={dirtyRoles.includes('research')}
                                        title="Unsaved changes"
                                    />
                                </span>
                            ),
                            'data-attr': 'signals-steering-research-tab',
                        },
                        {
                            key: 'implementation',
                            label: (
                                <span className="flex items-center gap-1">
                                    <IconCode aria-hidden />
                                    <span>Implementation</span>
                                    <LemonBadge
                                        size="xsmall"
                                        visible={dirtyRoles.includes('implementation')}
                                        title="Unsaved changes"
                                    />
                                </span>
                            ),
                            'data-attr': 'signals-steering-implementation-tab',
                        },
                        {
                            key: 'scout',
                            label: (
                                <span className="flex items-center gap-1">
                                    <IconCompass aria-hidden />
                                    <span>Scouts</span>
                                    <LemonBadge
                                        size="xsmall"
                                        visible={dirtyRoles.includes('scout')}
                                        title="Unsaved changes"
                                    />
                                </span>
                            ),
                            'data-attr': 'signals-steering-scout-tab',
                        },
                    ]}
                />
                <div className="flex flex-col gap-2">
                    <p className="m-0 text-xs text-secondary">{role.description}</p>
                    <InstructionsEditor
                        stored={storedInstructions}
                        value={instructions}
                        dirty={instructionsDirty}
                        loading={steeringConfigLoading}
                        placeholder={role.placeholder}
                        onChange={(value) => setDraft(selectedRole, value)}
                        onSave={submitInstructions}
                        onDiscard={() => discardDraft(selectedRole)}
                        discardDataAttr="signals-steering-discard"
                        dataAttr="signals-steering-instructions"
                        ariaLabel={role.title}
                    />
                    {storedInstructions === null && !steeringConfigLoading && (
                        <LemonButton onClick={loadSteeringConfig} size="small" data-attr="signals-steering-retry">
                            Retry
                        </LemonButton>
                    )}
                </div>
            </div>
        </SettingsSection>
    )
}
