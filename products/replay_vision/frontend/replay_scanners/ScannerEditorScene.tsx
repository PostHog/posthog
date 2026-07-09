import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import {
    HedgehogConstruction2,
    HedgehogImTheDriver,
    HedgehogMagnifyingGlass,
    HedgehogXRay,
} from '@posthog/brand/hoggies'
import { LemonButton, LemonInput, LemonSelect, LemonSwitch, LemonTag, LemonTextArea, Link } from '@posthog/lemon-ui'

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
import {
    SCANNER_EDITOR_STEP_ORDER,
    ScannerEditorStep,
    scannerEditorSceneLogic,
    scannerStepUrl,
} from './scannerEditorSceneLogic'
import { ScannerEditorStepper, STEP_LABELS } from './ScannerEditorStepper'
import { MODEL_OPTIONS, SCANNER_TYPE_OPTIONS } from './types'

export const scene: SceneExport = {
    component: ScannerEditorSceneComponent,
    logic: scannerEditorSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

// Template renders its own header, so only the form steps need one here.
const STEP_HEADERS: Record<
    Exclude<ScannerEditorStep, 'template'>,
    { hedgehog: JSX.Element; title: string; subtitle: string }
> = {
    configure: {
        hedgehog: <HedgehogMagnifyingGlass className="h-24 w-auto shrink-0" />,
        title: 'Configure your scanner',
        subtitle: 'What it looks for and how it analyzes recordings.',
    },
    triggers: {
        hedgehog: <HedgehogConstruction2 className="h-24 w-auto shrink-0" />,
        title: 'Set up scan conditions',
        subtitle: 'Pick which recordings to scan, and how often.',
    },
    self_driving: {
        hedgehog: <HedgehogImTheDriver className="h-24 w-auto shrink-0" />,
        title: 'Self-driving',
        subtitle: 'Close the loop: from findings to shipped fixes.',
    },
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

    const stepErrors: Record<ScannerEditorStep, boolean> = {
        template: false,
        self_driving: false,
        configure: showScannerErrors && !!(scannerValidationErrors?.name || scannerValidationErrors?.scanner_config),
        triggers: showScannerErrors && scannerValidationErrors?.sampling_rate != null,
    }

    // Validate the current step and move on: submit routes to the next visible step on success.
    const advance = (): void => {
        setSubmitIntent('advance')
        submitScanner()
    }

    const goToStep = (next: ScannerEditorStep): void => {
        if (isScannerSubmitting) {
            return
        }
        if (SCANNER_EDITOR_STEP_ORDER[next] > SCANNER_EDITOR_STEP_ORDER[step]) {
            if (step === 'template') {
                router.actions.push(urls.replayVisionScannerConfigure(scannerId))
                return
            }
            advance()
            return
        }
        router.actions.push(scannerStepUrl(next, scannerId))
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
                                    {STEP_HEADERS[step].hedgehog}
                                    <div>
                                        <div className="text-base font-semibold">{STEP_HEADERS[step].title}</div>
                                        <div className="text-sm text-muted">{STEP_HEADERS[step].subtitle}</div>
                                    </div>
                                </div>
                                {step === 'configure' ? (
                                    <ConfigureStep />
                                ) : step === 'triggers' ? (
                                    <ScannerTriggers scannerId={scannerId} />
                                ) : (
                                    <SelfDrivingStep />
                                )}
                                <EditorFooter
                                    step={step}
                                    scannerId={scannerId}
                                    visibleSteps={visibleSteps}
                                    isNew={isNew}
                                    isSubmitting={isScannerSubmitting}
                                    onAdvance={advance}
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

            <div className="flex flex-col gap-1 items-start">
                <LemonField name="model" label="Model" className="items-start">
                    <LemonSelect value={scanner.model} options={MODEL_OPTIONS} />
                </LemonField>
                <div className="text-xs text-muted">
                    Newer models tend to produce higher-quality observations, but cost more per observation.
                </div>
            </div>

            <ScannerTypeConfigEditor scannerId={scannerId} />
        </div>
    )
}

function SelfDrivingStep(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <p className="text-sm text-muted m-0">
                Don't just find problems, fix them. As this scanner reviews recordings, any issues it spots flow into
                PostHog Signals, where agents dig into the root cause and draft a pull request. You stay in control of
                what ships.{' '}
                <Link to="https://posthog.com/self-driving" target="_blank">
                    Learn more about PostHog self-driving
                </Link>
                .
            </p>
            <LemonField name="emits_signals">
                {({ value, onChange }) => (
                    <div className="flex items-center gap-3">
                        <LemonSwitch checked={!!value} onChange={onChange} />
                        <div>
                            <div className="text-sm font-medium">Emit findings as Signals</div>
                            <div className="text-xs text-muted">
                                Adds a side mission to each scan: clear, actionable product issues are emitted as
                                PostHog Signals to feed the self-driving loop.
                            </div>
                        </div>
                    </div>
                )}
            </LemonField>
        </div>
    )
}

function EditorFooter({
    step,
    scannerId,
    visibleSteps,
    isNew,
    isSubmitting,
    onAdvance,
    onSave,
}: {
    step: ScannerEditorStep
    scannerId: string
    visibleSteps: readonly ScannerEditorStep[]
    isNew: boolean
    isSubmitting: boolean
    onAdvance: () => void
    onSave: () => void
}): JSX.Element {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const stepIndex = visibleSteps.indexOf(step)
    const prevStep = stepIndex > 0 ? visibleSteps[stepIndex - 1] : null
    const nextStep = stepIndex < visibleSteps.length - 1 ? visibleSteps[stepIndex + 1] : null

    return (
        <div className="flex items-center justify-between">
            {/* First form step of a new scanner goes back to the template picker; a mid-flow step goes to the
                previous visible step; editing's first step (configure, no template) has no back. */}
            {isNew && step === 'configure' ? (
                <LemonButton type="tertiary" to={urls.replayVisionTemplates()} data-attr="vision-editor-back">
                    Back to templates
                </LemonButton>
            ) : prevStep ? (
                <LemonButton type="tertiary" to={scannerStepUrl(prevStep, scannerId)} data-attr="vision-editor-back">
                    Back
                </LemonButton>
            ) : null}
            {nextStep ? (
                <LemonButton
                    type="primary"
                    loading={isSubmitting}
                    onClick={onAdvance}
                    className="ml-auto"
                    data-attr="vision-editor-next"
                >
                    Next: {STEP_LABELS[nextStep]}
                </LemonButton>
            ) : (
                <LemonButton
                    type="primary"
                    loading={isSubmitting}
                    onClick={onSave}
                    className="ml-auto"
                    data-attr="vision-editor-save"
                    data-ph-capture-attribute-scanner-type={scanner?.scanner_type}
                >
                    {isNew ? 'Create scanner' : 'Save changes'}
                </LemonButton>
            )}
        </div>
    )
}

export default ScannerEditorSceneComponent
