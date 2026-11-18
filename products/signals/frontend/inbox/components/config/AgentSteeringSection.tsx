import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCode, IconCompass, IconSearch } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonTabs, Link } from '@posthog/lemon-ui'

import { useAnchor } from 'lib/hooks/useAnchor'
import { InstructionsEditor } from 'scenes/settings/environment/InstructionsEditor'
import { urls } from 'scenes/urls'

import { SandboxCustomImagesListOriginProduct } from 'products/tasks/frontend/generated/api.schemas'

import { SteeringRole, agentSteeringLogic } from '../../logics/agentSteeringLogic'
import type { SignalsCustomImageOrigin } from '../../logics/signalsCustomImagesLogic'
import { SettingsSection } from '../tabs/SettingsSection'
import { CustomImagePicker } from './CustomImagePicker'

export function AgentSteeringSection(): JSX.Element {
    const { location } = useValues(router)
    useAnchor(location.hash === '#steering' ? location.hash : '')
    const {
        selectedRole,
        storedInstructions,
        instructions,
        instructionsDirty,
        steeringConfig,
        steeringConfigLoading,
        dirtyRoles,
        storedCustomImageId,
    } = useValues(agentSteeringLogic)
    const { selectRole, setDraft, discardDraft, submitInstructions, loadSteeringConfig, saveCustomImage } =
        useActions(agentSteeringLogic)
    const roles: Record<
        SteeringRole,
        {
            title: string
            description: string
            placeholder: string
            imageOrigin: SignalsCustomImageOrigin
            imageDescription: string
        }
    > = {
        scout: {
            title: 'Scout instructions',
            description:
                'Scouts explore product data and connected sources, find problems and opportunities, and create signals or reports.',
            placeholder: 'For example: Focus on onboarding failures. Exclude demo accounts from impact estimates.',
            imageOrigin: SandboxCustomImagesListOriginProduct.SignalsScout,
            imageDescription: 'The image scout runs start from, unless a scout has its own.',
        },
        research: {
            title: 'Research instructions',
            description: 'Investigate signals, assess priority, and write reports.',
            placeholder: 'For example: Confirm whether the behavior is intentional before proposing a fix.',
            imageOrigin: SandboxCustomImagesListOriginProduct.SignalReport,
            imageDescription: 'The image research runs start from.',
        },
        implementation: {
            title: 'Implementation instructions',
            description:
                'Implementation agents turn reports into code changes, run checks, open pull requests, and address review feedback.',
            placeholder: 'For example: Keep changes focused. Add regression coverage and open draft pull requests.',
            imageOrigin: SandboxCustomImagesListOriginProduct.SignalReport,
            imageDescription: 'The image implementation runs start from.',
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
                    {steeringConfig !== null && (
                        <CustomImagePicker
                            origin={role.imageOrigin}
                            value={storedCustomImageId}
                            onChange={(imageId) => saveCustomImage({ role: selectedRole, imageId })}
                            label="Default image"
                            description={role.imageDescription}
                            defaultLabel="Standard image"
                            disabledReason={steeringConfigLoading ? 'Saving steering settings' : undefined}
                            dataAttr={`signals-steering-${selectedRole}-image`}
                        />
                    )}
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
