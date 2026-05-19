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

import { LensObservationsTable } from './components/LensObservationsTable'
import { LensTriggers } from './components/LensTriggers'
import { LensTypeConfigEditor } from './components/LensTypeConfigEditor'
import { replayLensLogic } from './replayLensLogic'
import { ReplayLensSceneLogicProps, replayLensSceneLogic } from './replayLensSceneLogic'
import { EditorTab, LENS_TYPE_OPTIONS, MODEL_OPTIONS } from './types'

export const scene: SceneExport<ReplayLensSceneLogicProps> = {
    component: ReplayLensSceneComponent,
    logic: replayLensSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

export function ReplayLensSceneComponent({ tabId }: { tabId: string }): JSX.Element {
    const { lensId, activeTab } = useValues(replayLensSceneLogic)
    const { setActiveTab } = useActions(replayLensSceneLogic)

    const lensLogic = replayLensLogic({ id: lensId, tabId })
    useAttachedLogic(lensLogic, replayLensSceneLogic)

    const { lens, originalLens, lensLoading, isLensSubmitting, hasUnsavedChanges, isNew } = useValues(lensLogic)
    const { setLensType, submitLens, resetLens, deleteLens } = useActions(lensLogic)

    if (lensLoading || !lens) {
        return (
            <SceneContent>
                <SceneTitleSection name="Loading…" resourceType={{ type: 'replay_vision' }} />
            </SceneContent>
        )
    }

    const tabs: (LemonTab<EditorTab> | false)[] = [
        {
            key: 'configuration',
            label: 'Configuration',
            content: (
                <div className="space-y-6 max-w-3xl">
                    <Field name="name" label="Name">
                        <LemonInput placeholder="e.g. Confused checkout flow" />
                    </Field>

                    <Field name="description" label="Description (optional)">
                        <LemonTextArea placeholder="What this lens looks for and why." minRows={2} />
                    </Field>

                    {isNew ? (
                        <Field name="lens_type" label="Lens type">
                            <LemonSelect
                                value={lens.lens_type}
                                onChange={(v) => setLensType(v)}
                                options={LENS_TYPE_OPTIONS.map((opt) => ({
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
                            <label className="block text-sm font-medium">Lens type</label>
                            <LemonTag type="option">
                                {LENS_TYPE_OPTIONS.find((o) => o.value === lens.lens_type)?.label ?? lens.lens_type}
                            </LemonTag>
                            <div className="text-xs text-muted">Lens type is fixed after creation.</div>
                        </div>
                    )}

                    <LensTypeConfigEditor lensId={lensId} tabId={tabId} />

                    <Field name="model" label="Model">
                        <LemonSelect value={lens.model} options={MODEL_OPTIONS} />
                    </Field>

                    <Field name="emits_signals">
                        {({ value, onChange }) => (
                            <div className="flex items-center gap-3">
                                <LemonSwitch checked={!!value} onChange={onChange} />
                                <div>
                                    <div className="text-sm font-medium">Emit PostHog Signals</div>
                                    <div className="text-xs text-muted">
                                        When on, the model also identifies actionable issues that feed into PostHog
                                        Signals.
                                    </div>
                                </div>
                            </div>
                        )}
                    </Field>
                </div>
            ),
        },
        {
            key: 'triggers',
            label: 'Triggers',
            content: <LensTriggers lensId={lensId} tabId={tabId} />,
        },
        !isNew && {
            key: 'observations' as EditorTab,
            label: 'Observations',
            content: <LensObservationsTable lensId={lensId} tabId={tabId} />,
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={lens.name || (isNew ? 'New lens' : 'Lens')}
                description={lens.description}
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
                                                title: `Delete "${lens.name || 'Untitled lens'}"?`,
                                                description: 'This cannot be undone.',
                                                primaryButton: {
                                                    children: 'Delete',
                                                    status: 'danger',
                                                    onClick: () => deleteLens(),
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
                        {hasUnsavedChanges && originalLens && (
                            <LemonButton type="secondary" size="small" onClick={() => resetLens(originalLens)}>
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
                                loading={isLensSubmitting}
                                onClick={() => submitLens()}
                                data-attr="save-replay-lens"
                            >
                                {isNew ? 'Create' : 'Save'}
                            </LemonButton>
                        </AccessControlAction>
                    </>
                }
            />

            {hasUnsavedChanges && !isNew && <LemonBanner type="info">You have unsaved changes.</LemonBanner>}

            <Form logic={replayLensLogic} props={{ id: lensId, tabId }} formKey="lens" enableFormOnSubmit>
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as EditorTab)}
                    tabs={tabs.filter((t): t is LemonTab<EditorTab> => Boolean(t))}
                />
            </Form>
        </SceneContent>
    )
}

export default ReplayLensSceneComponent
