import { useActions, useValues } from 'kea'

import { IconPencil, IconPlusSmall, IconPulse, IconTrash } from '@posthog/icons'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { BriefConfigModal } from './BriefConfigModal'
import { BriefsView } from './BriefsView'
import { pulseLogic } from './pulseLogic'
import { RunBriefButton } from './RunBriefButton'

export const scene: SceneExport = {
    component: PulseScene,
    logic: pulseLogic,
}

const PULSE_DESCRIPTION =
    'Your always-on product manager: it spots growth opportunities and shows you how to move the numbers that matter.'

export function PulseScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PULSE')
    const { briefConfigs, selectedConfigId, dataProcessingAccepted } = useValues(pulseLogic)
    const { selectConfig, openConfigModal } = useActions(pulseLogic)

    if (!isEnabled) {
        return <NotFound object="Pulse" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Pulse"
                description={PULSE_DESCRIPTION}
                resourceType={{ type: 'default_icon_type', forceIcon: <IconPulse /> }}
                actions={
                    <>
                        <LemonButton type="secondary" icon={<IconPlusSmall />} onClick={() => openConfigModal(null)}>
                            New config
                        </LemonButton>
                        <RunBriefButton />
                    </>
                }
            />

            {!dataProcessingAccepted && (
                <LemonBanner type="warning">
                    Pulse runs AI over your project data, and your organization has not approved AI data processing yet.
                    Approve it in{' '}
                    <Link to={urls.settings('organization-details', 'organization-ai-consent')}>
                        organization settings
                    </Link>{' '}
                    to generate briefs.
                </LemonBanner>
            )}

            {briefConfigs.length > 0 && (
                <div className="flex items-center gap-2">
                    <span className="text-muted">Focus</span>
                    <LemonSelect<string | null>
                        size="small"
                        value={selectedConfigId}
                        onChange={(value) => selectConfig(value)}
                        options={[
                            { value: null, label: 'Whole project' },
                            ...briefConfigs.map((config) => ({ value: config.id, label: config.name })),
                        ]}
                    />
                    {selectedConfigId !== null && <SelectedConfigActions selectedConfigId={selectedConfigId} />}
                </div>
            )}

            <BriefsView />
            <BriefConfigModal />
        </SceneContent>
    )
}

function SelectedConfigActions({ selectedConfigId }: { selectedConfigId: string }): JSX.Element | null {
    const { briefConfigs, configIdBeingDeleted } = useValues(pulseLogic)
    const { openConfigModal, deleteConfig } = useActions(pulseLogic)

    const selectedConfig = briefConfigs.find((config) => config.id === selectedConfigId)
    if (!selectedConfig) {
        return null
    }
    const isDeleting = configIdBeingDeleted === selectedConfig.id

    return (
        <>
            <LemonButton
                size="small"
                icon={<IconPencil />}
                tooltip="Edit config"
                onClick={() => openConfigModal(selectedConfig)}
            />
            <LemonButton
                size="small"
                status="danger"
                icon={<IconTrash />}
                tooltip="Delete config"
                loading={isDeleting}
                disabledReason={isDeleting ? 'Deleting…' : undefined}
                onClick={() =>
                    LemonDialog.open({
                        title: `Delete "${selectedConfig.name}"?`,
                        description: 'Briefs already generated for this config are kept.',
                        primaryButton: {
                            children: 'Delete',
                            status: 'danger',
                            onClick: () => deleteConfig(selectedConfig.id),
                        },
                        secondaryButton: { children: 'Cancel' },
                    })
                }
            />
        </>
    )
}
