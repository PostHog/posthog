import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTab,
    LemonTabs,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ScannerObservationsTable } from './components/ScannerObservationsTable'
import { ScannerTriggers } from './components/ScannerTriggers'
import { ScannerTypeConfigEditor } from './components/ScannerTypeConfigEditor'
import { replayScannerLogic } from './replayScannerLogic'
import { ReplayScannerSceneLogicProps, replayScannerSceneLogic } from './replayScannerSceneLogic'
import { EditorTab, SCANNER_TYPE_OPTIONS, MODEL_OPTIONS } from './types'

export const scene: SceneExport<ReplayScannerSceneLogicProps> = {
    component: ReplayScannerSceneComponent,
    logic: replayScannerSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

export function ReplayScannerSceneComponent({ tabId }: { tabId: string }): JSX.Element {
    const { scannerId, activeTab } = useValues(replayScannerSceneLogic)
    const { setActiveTab } = useActions(replayScannerSceneLogic)

    const scannerLogic = replayScannerLogic({ id: scannerId, tabId })
    useAttachedLogic(scannerLogic, replayScannerSceneLogic)

    const { scanner, originalScanner, scannerLoading, isScannerSubmitting, hasUnsavedChanges, isNew } =
        useValues(scannerLogic)
    const { setScannerType, submitScanner, resetScanner, deleteScanner } = useActions(scannerLogic)

    if (scannerLoading || !scanner) {
        return (
            <SceneContent>
                <SceneTitleSection name="Loading…" resourceType={{ type: 'replay_vision' }} />
            </SceneContent>
        )
    }

    const tabs: (LemonTab<EditorTab> | false)[] = [
        !isNew && {
            key: 'observations' as EditorTab,
            label: 'Observations',
            content: <ScannerObservationsTable scannerId={scannerId} tabId={tabId} />,
        },
        {
            key: 'triggers',
            label: 'Triggers',
            content: <ScannerTriggers scannerId={scannerId} tabId={tabId} />,
        },
        {
            key: 'configuration',
            label: 'Configuration',
            content: (
                <div className="space-y-6 max-w-3xl">
                    <Field name="name" label="Name">
                        <LemonInput placeholder="e.g. Confused checkout flow" />
                    </Field>

                    <Field name="description" label="Description (optional)">
                        <LemonTextArea placeholder="What this scanner looks for and why." minRows={2} />
                    </Field>

                    {isNew ? (
                        <Field name="scanner_type" label="Scanner type">
                            <LemonSelect
                                value={scanner.scanner_type}
                                onChange={(v) => setScannerType(v)}
                                options={SCANNER_TYPE_OPTIONS.map((opt) => ({
                                    value: opt.value,
                                    label: opt.label,
                                    labelInMenu: (
                                        <div className="flex flex-col">
                                            <span className="font-medium">{opt.label}</span>
                                            <span className="text-xs text-muted">{opt.description}</span>
                                        </div>
                                    ),
                                }))}
                            />
                        </Field>
                    ) : (
                        <div className="space-y-1">
                            <label className="block text-sm font-medium">Scanner type</label>
                            <LemonTag type="option">
                                {SCANNER_TYPE_OPTIONS.find((o) => o.value === scanner.scanner_type)?.label ??
                                    scanner.scanner_type}
                            </LemonTag>
                            <div className="text-xs text-muted">Scanner type is fixed after creation.</div>
                        </div>
                    )}

                    <ScannerTypeConfigEditor scannerId={scannerId} tabId={tabId} />

                    <Field name="model" label="Model">
                        <LemonSelect value={scanner.model} options={MODEL_OPTIONS} />
                    </Field>

                    <Field name="emits_signals">
                        {({ value, onChange }) => (
                            <div className="flex items-center gap-3">
                                <LemonSwitch checked={!!value} onChange={onChange} />
                                <div>
                                    <div className="text-sm font-medium">Emit PostHog Signals</div>
                                    <div className="text-xs text-muted">Also flags actionable issues as Signals.</div>
                                </div>
                            </div>
                        )}
                    </Field>
                </div>
            ),
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={scanner.name || (isNew ? 'New scanner' : 'Scanner')}
                description={scanner.description}
                resourceType={{ type: 'replay_vision' }}
                actions={
                    <>
                        {!isNew && (
                            <More
                                size="small"
                                overlay={
                                    <LemonButton
                                        status="danger"
                                        fullWidth
                                        onClick={() =>
                                            LemonDialog.open({
                                                title: `Delete "${scanner.name || 'Untitled scanner'}"?`,
                                                description: 'This cannot be undone.',
                                                primaryButton: {
                                                    children: 'Delete',
                                                    status: 'danger',
                                                    onClick: () => deleteScanner(),
                                                },
                                                secondaryButton: { children: 'Cancel' },
                                            })
                                        }
                                    >
                                        Delete
                                    </LemonButton>
                                }
                            />
                        )}
                        {hasUnsavedChanges && originalScanner && (
                            <LemonButton type="secondary" size="small" onClick={() => resetScanner(originalScanner)}>
                                Discard changes
                            </LemonButton>
                        )}
                        <AccessControlAction
                            resourceType={AccessControlResourceType.SessionRecording}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                size="small"
                                disabledReason={!isNew && !hasUnsavedChanges ? 'No changes to save' : undefined}
                                loading={isScannerSubmitting}
                                onClick={() => submitScanner()}
                                data-attr="save-replay-scanner"
                            >
                                {isNew ? 'Create' : 'Save'}
                            </LemonButton>
                        </AccessControlAction>
                    </>
                }
            />

            {hasUnsavedChanges && !isNew && <LemonBanner type="info">You have unsaved changes.</LemonBanner>}

            <Form logic={replayScannerLogic} props={{ id: scannerId, tabId }} formKey="scanner" enableFormOnSubmit>
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as EditorTab)}
                    tabs={tabs.filter((t): t is LemonTab<EditorTab> => Boolean(t))}
                />
            </Form>
        </SceneContent>
    )
}

export default ReplayScannerSceneComponent
