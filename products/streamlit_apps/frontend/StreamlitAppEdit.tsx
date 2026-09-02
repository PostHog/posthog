import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { StreamlitAppEditLogicProps, streamlitAppEditLogic } from './streamlitAppEditLogic'
import { StreamlitAppZipUpload } from './StreamlitAppZipUpload'

export const scene: SceneExport = {
    component: StreamlitAppEdit,
    logic: streamlitAppEditLogic,
    paramsToProps: ({ params: { id } }: { params: { id?: string } }): StreamlitAppEditLogicProps => ({
        shortId: id || 'new',
    }),
}

const CPU_OPTIONS = [
    { value: 0.25, label: '0.25 cores' },
    { value: 0.5, label: '0.5 cores' },
    { value: 1, label: '1 core' },
    { value: 2, label: '2 cores' },
    { value: 4, label: '4 cores' },
    { value: 8, label: '8 cores' },
]

const MEMORY_OPTIONS = [
    { value: 0.5, label: '0.5 GB' },
    { value: 1, label: '1 GB' },
    { value: 2, label: '2 GB' },
    { value: 4, label: '4 GB' },
    { value: 8, label: '8 GB' },
    { value: 16, label: '16 GB' },
]

export function StreamlitAppEdit(props: Record<string, any>): JSX.Element {
    const streamlitAppsFeatureFlagEnabled = useFeatureFlag('STREAMLIT_APPS')
    const shortId = (props.id as string) || 'new'
    const {
        streamlitApp,
        streamlitAppLoading,
        name,
        description,
        cpuCores,
        memoryGb,
        zipFile,
        versions,
        savedAppLoading,
    } = useValues(streamlitAppEditLogic({ shortId }))
    const {
        setName,
        setDescription,
        setCpuCores,
        setMemoryGb,
        setZipFile,
        setActiveVersionNumber,
        saveApp,
        deleteApp,
    } = useActions(streamlitAppEditLogic({ shortId }))

    if (!streamlitAppsFeatureFlagEnabled) {
        return <NotFound object="page" />
    }

    const isNew = shortId === 'new'

    if (!isNew && streamlitAppLoading) {
        return (
            <div className="flex items-center justify-center py-20">
                <Spinner className="text-4xl" />
            </div>
        )
    }

    const canSave = name.trim().length > 0 && (isNew ? !!zipFile : true)

    return (
        <div>
            <SceneTitleSection
                name={isNew ? 'New app' : (streamlitApp?.name ?? 'Edit app')}
                resourceType={{ type: 'streamlit_app' }}
            />
            <div className="max-w-xl space-y-6">
                <div className="space-y-2">
                    <LemonLabel htmlFor="streamlit-app-name">Name</LemonLabel>
                    <LemonInput id="streamlit-app-name" value={name} onChange={setName} placeholder="My app" />
                </div>

                <div className="space-y-2">
                    <LemonLabel htmlFor="streamlit-app-description">Description</LemonLabel>
                    <LemonTextArea
                        id="streamlit-app-description"
                        value={description}
                        onChange={setDescription}
                        placeholder="What does this app do?"
                    />
                </div>

                <div className="space-y-2">
                    <LemonLabel>{isNew ? 'Upload' : 'Upload new version'}</LemonLabel>
                    <StreamlitAppZipUpload file={zipFile} onFileChange={setZipFile} />
                </div>

                {!isNew && versions.length > 0 && (
                    <div className="space-y-2">
                        <LemonLabel>Active version</LemonLabel>
                        <LemonSelect
                            value={streamlitApp?.active_version?.version_number}
                            onChange={(value) => {
                                if (value !== null && value !== undefined) {
                                    setActiveVersionNumber(value)
                                }
                            }}
                            options={versions.map((v: { version_number: number; created_at: string }) => ({
                                value: v.version_number,
                                label: `v${v.version_number} — ${humanFriendlyDetailedTime(v.created_at)}`,
                            }))}
                        />
                    </div>
                )}

                <div className="space-y-2">
                    <LemonLabel>Resources</LemonLabel>
                    <div className="flex gap-4">
                        <div className="flex-1 space-y-1">
                            <span className="text-sm text-muted">CPU</span>
                            <LemonSelect value={cpuCores} onChange={setCpuCores} options={CPU_OPTIONS} fullWidth />
                        </div>
                        <div className="flex-1 space-y-1">
                            <span className="text-sm text-muted">Memory</span>
                            <LemonSelect value={memoryGb} onChange={setMemoryGb} options={MEMORY_OPTIONS} fullWidth />
                        </div>
                    </div>
                </div>

                <div className="flex justify-between pt-4">
                    {!isNew ? (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Delete app?',
                                    description:
                                        'This will permanently delete this app and all its versions. This cannot be undone.',
                                    primaryButton: {
                                        children: 'Delete',
                                        status: 'danger',
                                        onClick: () => deleteApp(),
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                })
                            }}
                        >
                            Delete
                        </LemonButton>
                    ) : (
                        <div />
                    )}
                    <div className="flex gap-2">
                        <LemonButton type="secondary" to={urls.streamlitApps()}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={saveApp}
                            loading={savedAppLoading}
                            disabledReason={!canSave ? 'Fill in all required fields' : undefined}
                        >
                            {isNew ? 'Create app' : 'Save changes'}
                        </LemonButton>
                    </div>
                </div>
            </div>
        </div>
    )
}
