import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTab,
    LemonTabs,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

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

export function ReplayLensSceneComponent(): JSX.Element {
    const { lensId, activeTab } = useValues(replayLensSceneLogic)
    const { setActiveTab } = useActions(replayLensSceneLogic)

    const lensLogic = replayLensLogic({ id: lensId })
    useAttachedLogic(lensLogic, replayLensSceneLogic)

    const { lens, lensLoading, lensSubmitting, formValid, hasUnsavedChanges, isNew } = useValues(lensLogic)
    const { setName, setDescription, setLensType, setLensConfig, setModel, setEmitsSignals, saveLens, resetLens } =
        useActions(lensLogic)
    const { push } = useActions(router)

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
                <Form logic={replayLensLogic} props={{ id: lensId }} formKey="lens" className="space-y-6 max-w-3xl">
                    <Field name="name" label="Name">
                        <LemonInput value={lens.name} onChange={setName} placeholder="e.g. Confused checkout flow" />
                    </Field>

                    <Field name="description" label="Description (optional)">
                        <LemonTextArea
                            value={lens.description ?? ''}
                            onChange={setDescription}
                            placeholder="What this lens looks for and why."
                            minRows={2}
                        />
                    </Field>

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

                    <LensTypeConfigEditor lens={lens} onChange={setLensConfig} />

                    <Field name="model" label="Model">
                        <LemonSelect value={lens.model} onChange={(v) => setModel(v)} options={MODEL_OPTIONS} />
                    </Field>

                    <Field name="emits_signals" label="Emit PostHog Signals">
                        <div className="flex items-center gap-3">
                            <LemonSwitch checked={lens.emits_signals} onChange={setEmitsSignals} />
                            <div className="text-xs text-muted">
                                When on, the model also identifies actionable issues that feed into PostHog Signals.
                            </div>
                        </div>
                    </Field>
                </Form>
            ),
        },
        {
            key: 'triggers',
            label: 'Triggers',
            content: <LensTriggers />,
        },
        !isNew && {
            key: 'observations' as EditorTab,
            label: 'Observations',
            content: <LensObservationsTable />,
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={lens.name || (isNew ? 'New lens' : 'Lens')}
                description={lens.description}
                resourceType={{ type: 'replay_vision' }}
                actions={
                    <div className="flex gap-2">
                        <LemonButton type="tertiary" onClick={() => push(urls.replayLenses())}>
                            Cancel
                        </LemonButton>
                        {!isNew && hasUnsavedChanges && (
                            <LemonButton type="secondary" onClick={() => resetLens()}>
                                Reset
                            </LemonButton>
                        )}
                        <AccessControlAction
                            resourceType={AccessControlResourceType.SessionRecording}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                disabledReason={
                                    !formValid ? 'Set a name, prompt, and a sampling rate above 0.' : undefined
                                }
                                loading={lensSubmitting}
                                onClick={() => saveLens()}
                                data-attr="save-replay-lens"
                            >
                                {isNew ? 'Create lens' : 'Save changes'}
                            </LemonButton>
                        </AccessControlAction>
                    </div>
                }
            />

            {hasUnsavedChanges && !isNew && <LemonBanner type="info">You have unsaved changes.</LemonBanner>}

            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key as EditorTab)}
                tabs={tabs.filter((t): t is LemonTab<EditorTab> => Boolean(t))}
            />
        </SceneContent>
    )
}

export default ReplayLensSceneComponent
