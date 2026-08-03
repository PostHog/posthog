import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { TZLabel } from 'lib/components/TZLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { ConfigVersionApi, LabelSummaryApi } from '../generated/api.schemas'
import { aiEnrichmentLogic } from './aiEnrichmentLogic'

export const scene: SceneExport = {
    component: AIEnrichmentScene,
    logic: aiEnrichmentLogic,
}

function AIEnrichmentLabelPicker(): JSX.Element {
    const { labels, labelsLoading } = useValues(aiEnrichmentLogic)
    const results = labels?.results ?? []

    const columns: LemonTableColumns<LabelSummaryApi> = [
        {
            title: 'Label',
            key: 'label',
            render: (_, row) => <Link to={urls.aiEnrichment(row.label)}>{row.label}</Link>,
        },
        { title: 'Versions', key: 'version_count', dataIndex: 'version_count' },
        {
            title: 'Active version',
            key: 'active_version',
            render: (_, row) => row.active_version ?? <span className="text-secondary">None</span>,
        },
    ]

    return (
        <div className="space-y-2">
            <h3 className="mb-0">Pick a label</h3>
            <LemonTable
                dataSource={results}
                loading={labelsLoading}
                rowKey={(row) => row.label}
                columns={columns}
                emptyState="No labels have any saved prompt configs yet."
            />
        </div>
    )
}

function AIEnrichmentVersionRail(): JSX.Element {
    const { selectedLabel, versions, configsLoading, selectedVersion, activateResultLoading } =
        useValues(aiEnrichmentLogic)
    const { activateVersion } = useActions(aiEnrichmentLogic)

    const columns: LemonTableColumns<ConfigVersionApi> = [
        {
            title: 'Version',
            key: 'version',
            render: (_, version) => (
                <div className="flex items-center gap-1">
                    <span className="font-semibold">{version.version}</span>
                    {version.is_active && <LemonTag type="success">ACTIVE</LemonTag>}
                </div>
            ),
        },
        {
            title: 'Created',
            key: 'created_at',
            render: (_, version) => (
                <span className="text-secondary text-xs">
                    {version.created_by_email ?? 'system'} · <TZLabel time={version.created_at} />
                </span>
            ),
        },
        {
            title: '',
            key: 'actions',
            render: (_, version) =>
                version.is_active ? null : (
                    <LemonButton
                        type="secondary"
                        size="small"
                        disabledReason={activateResultLoading ? 'Activation in progress' : undefined}
                        onClick={() =>
                            LemonDialog.open({
                                title: `Activate version ${version.version}?`,
                                description:
                                    'The batch runner will start computing this version instead of the currently active one.',
                                primaryButton: {
                                    children: 'Activate',
                                    onClick: () => activateVersion(version.id),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                    >
                        Activate
                    </LemonButton>
                ),
        },
    ]

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2">
                <h3 className="mb-0">{selectedLabel}</h3>
                {selectedVersion && (
                    <span className="text-secondary text-xs">
                        Live version: <span className="font-semibold">{selectedVersion.version}</span>
                    </span>
                )}
            </div>
            <LemonTable
                dataSource={versions}
                loading={configsLoading}
                rowKey={(version) => version.id}
                columns={columns}
                emptyState="No versions saved yet for this label."
            />
        </div>
    )
}

export function AIEnrichmentScene(): JSX.Element {
    const { user } = useValues(userLogic)
    const { selectedLabel } = useValues(aiEnrichmentLogic)

    if (!user?.is_staff) {
        return <AccessDenied object="page" reason="This page is only accessible to staff users." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="AI enrichment"
                description="See which classifier version is live for a label, and switch which one is live."
                resourceType={{ type: 'llm_analytics' }}
            />
            {selectedLabel ? <AIEnrichmentVersionRail /> : <AIEnrichmentLabelPicker />}
        </SceneContent>
    )
}
