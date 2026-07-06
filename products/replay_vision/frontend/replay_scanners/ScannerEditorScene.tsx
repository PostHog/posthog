import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { HedgehogConstruction2, HedgehogMagnifyingGlass, HedgehogXRay } from '@posthog/brand/hoggies'
import {
    LemonButton,
    LemonCollapse,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ReplayVisionFeedbackButton } from '../components/ReplayVisionFeedbackButton'
import { ScannerTemplatePicker } from './components/ScannerTemplatePicker'
import { ScannerTriggers } from './components/ScannerTriggers'
import { ScannerTypeConfigEditor } from './components/ScannerTypeConfigEditor'
import { replayScannerLogic } from './replayScannerLogic'
import { SCANNER_EDITOR_STEP_ORDER, ScannerEditorStep, scannerEditorSceneLogic } from './scannerEditorSceneLogic'
import { ScannerEditorStepper } from './ScannerEditorStepper'
import { MODEL_OPTIONS, SCANNER_TYPE_OPTIONS } from './types'

export const scene: SceneExport = {
    component: ScannerEditorSceneComponent,
    logic: scannerEditorSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

export function ScannerEditorSceneComponent(): JSX.Element {
    const { scannerId, step, isNew, visibleSteps } = useValues(scannerEditorSceneLogic)

    const scannerLogic = replayScannerLogic({ id: scannerId })
    useAttachedLogic(scannerLogic, scannerEditorSceneLogic)

    const { scanner, scannerLoading, isScannerSubmitting, scannerValidationErrors, showScannerErrors } =
        useValues(scannerLogic)
    const { submitScanner, setSubmitIntent } = useActions(scannerLogic)

    if (step !== 'template' && (scannerLoading || !scanner)) {
        return (
            <SceneContent>
                <SceneTitleSection name="Loading…" resourceType={{ type: 'replay_vision' }} />
            </SceneContent>
        )
    }

    const title = isNew ? scanner?.name || 'New scanner' : scanner?.name || 'Scanner'

    const stepErrors = showScannerErrors
        ? {
              template: false,
              configure: !!(scannerValidationErrors?.name || scannerValidationErrors?.scanner_config),
              triggers: scannerValidationErrors?.sampling_rate != null,
          }
        : { template: false, configure: false, triggers: false }

    const goToStep = (next: ScannerEditorStep): void => {
        if (isScannerSubmitting) {
            return
        }
        // Clicking the step you're already on is a deliberate no-op; re-pushing the current route does nothing visible.
        if (next === step) {
            return
        }
        if (SCANNER_EDITOR_STEP_ORDER[next] > SCANNER_EDITOR_STEP_ORDER[step]) {
            if (step === 'template') {
                router.actions.push(urls.replayVisionScannerConfigure(scannerId))
                return
            }
            setSubmitIntent('advance')
            submitScanner()
            return
        }
        if (next === 'template') {
            router.actions.push(urls.replayVisionScannerTemplate(scannerId))
            return
        }
        router.actions.push(
            next === 'configure'
                ? urls.replayVisionScannerConfigure(scannerId)
                : urls.replayVisionScannerTriggers(scannerId)
        )
    }

    return (
        <SceneContent>
            <div className="flex flex-col items-center pt-16 pb-8">
                <div className="w-full max-w-5xl px-4 flex flex-col gap-6">
                    <SceneTitleSection
                        name={title}
                        resourceType={{ type: 'replay_vision' }}
                        actions={<ReplayVisionFeedbackButton />}
                    />
                    <ScannerEditorStepper
                        currentStep={step}
                        steps={visibleSteps}
                        onStepClick={goToStep}
                        stepErrors={stepErrors}
                    />
                    {step === 'template' ? (
                        <>
                            <div className="text-center space-y-3">
                                <div className="flex justify-center mb-2">
                                    <HedgehogXRay className="w-32 h-32" />
                                </div>
                                <h1 className="text-2xl font-bold m-0">Choose a scanner template</h1>
                                <p className="text-base text-secondary max-w-2xl mx-auto m-0">
                                    Pick a pre-configured template to get started quickly, or create a fully custom
                                    scanner from scratch.
                                </p>
                            </div>
                            <ScannerTemplatePicker />
                        </>
                    ) : (
                        <Form
                            logic={replayScannerLogic}
                            props={{ id: scannerId }}
                            formKey="scanner"
                            enableFormOnSubmit
                            className="max-w-4xl w-full mx-auto"
                        >
                            <div className="bg-bg-light border rounded-lg shadow-sm p-6 flex flex-col gap-6 [&_.Field--error_.input-like]:!border-danger">
                                <div className="flex items-center gap-3">
                                    {step === 'configure' ? (
                                        <HedgehogMagnifyingGlass className="h-24 w-auto shrink-0" />
                                    ) : (
                                        <HedgehogConstruction2 className="h-24 w-auto shrink-0" />
                                    )}
                                    <div>
                                        <div className="text-base font-semibold">
                                            {step === 'configure' ? 'Configure your scanner' : 'Set up triggers'}
                                        </div>
                                        <div className="text-sm text-muted">
                                            {step === 'configure'
                                                ? 'What it looks for and how it analyzes recordings.'
                                                : 'Pick which recordings to scan, and how often.'}
                                        </div>
                                    </div>
                                </div>
                                {step === 'configure' ? <ConfigureStep /> : <ScannerTriggers scannerId={scannerId} />}
                                <EditorFooter
                                    step={step}
                                    scannerId={scannerId}
                                    isNew={isNew}
                                    isSubmitting={isScannerSubmitting}
                                    onAdvance={() => {
                                        setSubmitIntent('advance')
                                        submitScanner()
                                    }}
                                    onSave={() => {
                                        setSubmitIntent('save')
                                        submitScanner()
                                    }}
                                />
                            </div>
                        </Form>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}

function ConfigureStep(): JSX.Element {
    const { scannerId } = useValues(scannerEditorSceneLogic)
    const { scanner, isNew } = useValues(replayScannerLogic({ id: scannerId }))
    const { setScannerType } = useActions(replayScannerLogic({ id: scannerId }))
    const { searchParams } = useValues(router)
    const isTypeSelectable = isNew && !searchParams.template

    if (!scanner) {
        return <></>
    }

    return (
        <div className="flex flex-col gap-4">
            <LemonField name="name" label="Name">
                <LemonInput placeholder="e.g. Confused checkout flow" />
            </LemonField>

            <LemonField name="description" label="Description (optional)">
                <LemonTextArea placeholder="What this scanner looks for and why." minRows={2} />
            </LemonField>

            {isTypeSelectable ? (
                <LemonField name="scanner_type" label="Scanner type" className="items-start">
                    <LemonSelect
                        data-attr="vision-editor-type-select"
                        value={scanner.scanner_type}
                        onChange={(next) => {
                            if (next === scanner.scanner_type) {
                                return
                            }
                            if (scanner.scanner_config?.prompt?.trim()) {
                                LemonDialog.open({
                                    title: 'Switch scanner type?',
                                    description:
                                        'Your prompt and type-specific settings will reset to defaults for the new type.',
                                    primaryButton: {
                                        children: 'Switch and reset',
                                        onClick: () => setScannerType(next),
                                    },
                                    secondaryButton: { children: 'Keep current' },
                                })
                                return
                            }
                            setScannerType(next)
                        }}
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
                </LemonField>
            ) : (
                <div className="space-y-1">
                    <label className="block text-sm font-medium">Scanner type</label>
                    <LemonTag type="option">
                        {SCANNER_TYPE_OPTIONS.find((o) => o.value === scanner.scanner_type)?.label ??
                            scanner.scanner_type}
                    </LemonTag>
                    <div className="text-xs text-muted">
                        {isNew ? (
                            <>
                                Type is set by the template you picked. To use a different type,{' '}
                                <Link to={urls.replayVisionTemplates()}>start from another template</Link>.
                            </>
                        ) : (
                            'Scanner type is fixed after creation.'
                        )}
                    </div>
                </div>
            )}

            <ScannerTypeConfigEditor scannerId={scannerId} />

            <LemonCollapse
                panels={[
                    {
                        key: 'advanced',
                        header: 'Advanced',
                        content: (
                            <div className="flex flex-col gap-4">
                                <LemonField name="model" label="Model" className="items-start">
                                    <LemonSelect value={scanner.model} options={MODEL_OPTIONS} />
                                </LemonField>
                                <LemonField name="emits_signals">
                                    {({ value, onChange }) => (
                                        <div className="flex items-center gap-3">
                                            <LemonSwitch checked={!!value} onChange={onChange} />
                                            <div>
                                                <div className="text-sm font-medium">Hand off to Responder agents</div>
                                                <div className="text-xs text-muted">
                                                    Adds a side mission to each scan: clear, actionable product issues
                                                    are handled by PostHog Responder agents.
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </LemonField>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}

function EditorFooter({
    step,
    scannerId,
    isNew,
    isSubmitting,
    onAdvance,
    onSave,
}: {
    step: ScannerEditorStep
    scannerId: string
    isNew: boolean
    isSubmitting: boolean
    onAdvance: () => void
    onSave: () => void
}): JSX.Element {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    return (
        <div className="flex items-center justify-between">
            {step === 'configure' ? (
                <>
                    {isNew && (
                        <LemonButton type="tertiary" to={urls.replayVisionTemplates()} data-attr="vision-editor-back">
                            Back to templates
                        </LemonButton>
                    )}
                    <LemonButton
                        type="primary"
                        loading={isSubmitting}
                        onClick={onAdvance}
                        className="ml-auto"
                        data-attr="vision-editor-next"
                    >
                        Next: triggers
                    </LemonButton>
                </>
            ) : (
                <>
                    <LemonButton
                        type="tertiary"
                        to={urls.replayVisionScannerConfigure(scannerId)}
                        data-attr="vision-editor-back"
                    >
                        Back
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={isSubmitting}
                        onClick={onSave}
                        data-attr="vision-editor-save"
                        data-ph-capture-attribute-scanner-type={scanner?.scanner_type}
                    >
                        {isNew ? 'Create scanner' : 'Save changes'}
                    </LemonButton>
                </>
            )}
        </div>
    )
}

export default ScannerEditorSceneComponent
