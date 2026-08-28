import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useState } from 'react'

import * as construction2Png from '@posthog/brand/hoggies/png/construction-2'
import * as imTheDriverPng from '@posthog/brand/hoggies/png/im-the-driver'
import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass-1'
import * as moneyPng from '@posthog/brand/hoggies/png/money'
import * as reporterPng from '@posthog/brand/hoggies/png/reporter'
import * as xRayPng from '@posthog/brand/hoggies/png/x-ray'
import { IconSparkles } from '@posthog/icons'
import {
    LemonButton,
    LemonCard,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { tagsModel } from '~/models/tagsModel'
import { ProductKey } from '~/queries/schema/schema-general'

import { CreditPriceNote } from '../components/PricingLink'
import { ReplayVisionFeedbackButton } from '../components/ReplayVisionFeedbackButton'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { ScannerBudget } from './components/ScannerBudget'
import { ScannerGoalDraft } from './components/ScannerGoalDraft'
import { ScannerGoalFlow } from './components/ScannerGoalFlow'
import { ScannerGoalOverview } from './components/ScannerGoalOverview'
import { ScannerTemplatePicker } from './components/ScannerTemplatePicker'
import { ScannerTriggers } from './components/ScannerTriggers'
import { ScannerTypeConfigEditor } from './components/ScannerTypeConfigEditor'
import { replayScannerLogic } from './replayScannerLogic'
import {
    SCANNER_EDITOR_STEPS,
    SCANNER_EDITOR_STEP_ORDER,
    STEP_LABELS,
    ScannerEditorStep,
    UNVALIDATED_SCANNER_STEPS,
    scannerStepErrors,
    scannerEditorSceneLogic,
    scannerStepUrlWithParams,
} from './scannerEditorSceneLogic'
import { ScannerEditorStepper } from './ScannerEditorStepper'
import { scannerSelfDrivingStatsLogic } from './scannerSelfDrivingStatsLogic'
import { SCANNER_TYPE_OPTIONS, getModelOptions, modelNamingVariant } from './types'

const HedgehogConstruction2 = pngHoggie(construction2Png)
const HedgehogImTheDriver = pngHoggie(imTheDriverPng)
const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)
const HedgehogReporter = pngHoggie(reporterPng)
const HedgehogMoney = pngHoggie(moneyPng)
const HedgehogXRay = pngHoggie(xRayPng)

export const scene: SceneExport = {
    component: ScannerEditorSceneComponent,
    logic: scannerEditorSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

// Template renders its own header, and overview renders none, so only the form steps need one here.
const STEP_HEADERS: Record<
    Exclude<ScannerEditorStep, 'template' | 'overview'>,
    { hedgehog: JSX.Element; title: string; subtitle: string }
> = {
    details: {
        hedgehog: <HedgehogReporter className="h-16 sm:h-24 w-auto shrink-0" />,
        title: 'Name your scanner',
        subtitle: 'All optional. Tags help you find it later in the scanner list.',
    },
    configure: {
        hedgehog: <HedgehogMagnifyingGlass className="h-16 sm:h-24 w-auto shrink-0" />,
        title: 'Configure your scanner',
        subtitle: 'What it looks for and how it analyzes recordings.',
    },
    triggers: {
        hedgehog: <HedgehogConstruction2 className="h-16 sm:h-24 w-auto shrink-0" />,
        title: 'Pick the recordings to scan',
        subtitle: 'Narrow down which sessions this scanner watches.',
    },
    budget: {
        hedgehog: <HedgehogMoney className="h-16 sm:h-24 w-auto shrink-0" />,
        title: 'Set your budget',
        subtitle: 'How much of the matching traffic to scan, and what to spend on it.',
    },
}

export function ScannerEditorSceneComponent(): JSX.Element {
    const { scannerId, step, isNew } = useValues(scannerEditorSceneLogic)
    const { searchParams } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    // Multivariate flag; a truthy check would turn the goal flow on for control too.
    const goalFlow = featureFlags[FEATURE_FLAGS.VISION_GOAL_BASED_CREATION_FLOW] === 'test'
    const [manualMode, setManualMode] = useState(false)
    const showGoalEntry = step === 'template' && goalFlow && !manualMode
    // Reached a form step by clicking Edit on the goal overview: the overview is home, not a wizard
    // stop, so the linear stepper is hidden and the footer returns there instead of marching on.
    const fromOverview = searchParams.from === 'overview'

    const scannerLogic = replayScannerLogic({ id: scannerId })
    useAttachedLogic(scannerLogic, scannerEditorSceneLogic)

    const {
        scanner,
        scannerLoading,
        isScannerSubmitting,
        scannerValidationErrors,
        showScannerErrors,
        durationValidationError,
    } = useValues(scannerLogic)
    const { submitScanner } = useActions(scannerLogic)

    if (step !== 'template' && (scannerLoading || !scanner)) {
        return (
            <SceneContent>
                <SceneTitleSection name="Loading…" resourceType={{ type: 'replay_vision' }} />
            </SceneContent>
        )
    }

    const title = isNew ? scanner?.name || 'New scanner' : scanner?.name || 'Scanner'

    const stepErrors = showScannerErrors
        ? scannerStepErrors({ ...scannerValidationErrors, duration: durationValidationError })
        : undefined

    // Validate the current step and move on: submit routes to the next step on success. A step with
    // nothing to validate navigates straight on, so it can't fail on fields the user hasn't reached.
    const advance = (): void => {
        if (UNVALIDATED_SCANNER_STEPS.includes(step)) {
            const next = SCANNER_EDITOR_STEPS[SCANNER_EDITOR_STEPS.indexOf(step) + 1]
            if (next) {
                router.actions.push(scannerStepUrlWithParams(next, scannerId, searchParams))
                return
            }
        }
        submitScanner()
    }

    const goToStep = (next: ScannerEditorStep): void => {
        if (isScannerSubmitting) {
            return
        }
        if (SCANNER_EDITOR_STEP_ORDER[next] > SCANNER_EDITOR_STEP_ORDER[step]) {
            if (step === 'template') {
                router.actions.push(urls.replayVisionScannerDetails(scannerId))
                return
            }
            advance()
            return
        }
        router.actions.push(scannerStepUrlWithParams(next, scannerId, searchParams))
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
                    {showGoalEntry || step === 'overview' || fromOverview ? null : (
                        <ScannerEditorStepper
                            currentStep={step}
                            steps={SCANNER_EDITOR_STEPS}
                            onStepClick={goToStep}
                            stepErrors={stepErrors}
                            disabledSteps={
                                isNew
                                    ? undefined
                                    : { template: 'A saved scanner keeps the template it was created from' }
                            }
                        />
                    )}
                    {step === 'template' ? (
                        showGoalEntry ? (
                            <>
                                <div className="text-center space-y-3">
                                    <div className="flex justify-center mb-2">
                                        <HedgehogXRay className="w-32 h-32" />
                                    </div>
                                    <h1 className="text-2xl font-bold m-0">What should the scanner find out?</h1>
                                    <p className="text-base text-secondary max-w-2xl mx-auto m-0">
                                        Describe the goal, set a monthly budget, and the agent drafts the whole scanner
                                        for you to review.
                                    </p>
                                </div>
                                <ScannerGoalFlow onManual={() => setManualMode(true)} />
                            </>
                        ) : (
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
                                <ScannerGoalDraft />
                            </>
                        )
                    ) : step === 'overview' ? (
                        <div className="max-w-4xl w-full mx-auto">
                            <ScannerGoalOverview scannerId={scannerId} />
                        </div>
                    ) : (
                        <Form
                            logic={replayScannerLogic}
                            props={{ id: scannerId }}
                            formKey="scanner"
                            enableFormOnSubmit
                            className="max-w-4xl w-full mx-auto"
                        >
                            <div className="bg-bg-light border rounded-lg shadow-sm p-4 sm:p-6 flex flex-col gap-6 [&_.Field--error_.input-like]:!border-danger">
                                <div className="flex items-center gap-3">
                                    {STEP_HEADERS[step].hedgehog}
                                    <div>
                                        <div className="text-base font-semibold">{STEP_HEADERS[step].title}</div>
                                        <div className="text-sm text-muted">{STEP_HEADERS[step].subtitle}</div>
                                    </div>
                                </div>
                                {step === 'details' ? (
                                    <DetailsStep />
                                ) : step === 'configure' ? (
                                    <ConfigureStep />
                                ) : step === 'triggers' ? (
                                    <ScannerTriggers scannerId={scannerId} />
                                ) : (
                                    <ScannerBudget scannerId={scannerId} />
                                )}
                                <EditorFooter
                                    step={step}
                                    scannerId={scannerId}
                                    isNew={isNew}
                                    isSubmitting={isScannerSubmitting}
                                    onAdvance={advance}
                                    onSave={() => submitScanner()}
                                />
                            </div>
                        </Form>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}

function DetailsStep(): JSX.Element {
    const { tags: allTags } = useValues(tagsModel)

    return (
        <div className="flex flex-col gap-4">
            <LemonField name="name" label="Name (optional)">
                <LemonInput placeholder="e.g. Checkout friction" />
            </LemonField>

            <LemonField
                name="description"
                label="Description (optional)"
                help="The scanning agent doesn't see this field. It's for you and your team to keep scanners organized."
            >
                <LemonTextArea placeholder="What this scanner looks for and why." minRows={2} />
            </LemonField>

            <LemonField
                name="tags"
                label="Tags (optional)"
                help="For organizing and filtering the scanner list. The scanning agent doesn't see them."
            >
                {({ value, onChange }) => (
                    <ObjectTags
                        tags={value ?? []}
                        onChange={onChange}
                        saving={false}
                        // Tags from other products can contain commas; the scanner API rejects those.
                        tagsAvailable={allTags.filter((tag) => !tag.includes(',') && !value?.includes(tag))}
                        data-attr="vision-editor-tags"
                    />
                )}
            </LemonField>
        </div>
    )
}

// Live outcomes under the self-driving toggle: what turning it on has already produced. Renders
// nothing until the scanner has emitted at least one signal, so a new scanner just sees the pitch.
function SelfDrivingOutcomesLine({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { selfDrivingStats } = useValues(scannerSelfDrivingStatsLogic({ scannerId }))
    if (!selfDrivingStats || selfDrivingStats.signals_emitted === 0) {
        return null
    }
    const { signals_emitted, reports_contributed, prs_opened, prs_merged } = selfDrivingStats
    return (
        <div className="text-xs text-muted" data-attr="vision-editor-self-driving-outcomes">
            So far this scanner has emitted <strong className="tabular-nums">{signals_emitted.toLocaleString()}</strong>{' '}
            {pluralize(signals_emitted, 'signal', undefined, false)}, contributing to{' '}
            <strong className="tabular-nums">{reports_contributed.toLocaleString()}</strong>{' '}
            {pluralize(reports_contributed, 'report', undefined, false)} and{' '}
            <strong className="tabular-nums">{prs_opened.toLocaleString()}</strong>{' '}
            {pluralize(prs_opened, 'PR', undefined, false)}
            {prs_opened > 0 ? <> ({prs_merged.toLocaleString()} merged)</> : null}.
        </div>
    )
}

function ConfigureStep(): JSX.Element {
    const { scannerId } = useValues(scannerEditorSceneLogic)
    const { scanner, isNew, goalDraft } = useValues(replayScannerLogic({ id: scannerId }))
    const { setScannerType } = useActions(replayScannerLogic({ id: scannerId }))
    const { searchParams } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const namingVariant = modelNamingVariant(featureFlags[FEATURE_FLAGS.REPLAY_VISION_MODEL_TIER_NAMING_EXPERIMENT])
    const isTypeSelectable = isNew && !searchParams.template

    if (!scanner) {
        return <></>
    }

    return (
        <div className="flex flex-col gap-4">
            {isNew && goalDraft?.rationale ? (
                <div
                    className="flex items-start gap-2 rounded border border-[var(--color-ai)] p-3 text-sm"
                    data-attr="vision-goal-draft-rationale"
                >
                    <IconSparkles className="text-ai mt-0.5 size-4 shrink-0" />
                    <span>{goalDraft.rationale}</span>
                </div>
            ) : null}
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
                    <LemonSelect
                        className="max-w-full"
                        value={scanner.model}
                        options={getModelOptions(namingVariant)}
                    />
                </LemonField>
                {/* The price line stays outside the variant branch so every arm of the model-naming experiment
                    shows it. Tier names give even less of a cost anchor than provider model names do. */}
                <div className="text-xs text-muted">
                    {namingVariant
                        ? 'Higher tiers tend to produce higher-quality observations, but cost more per observation.'
                        : 'Newer models tend to produce higher-quality observations, but cost more per observation.'}{' '}
                    <CreditPriceNote dataAttr="vision-pricing-link-model-picker" />
                </div>
            </div>

            <ScannerTypeConfigEditor scannerId={scannerId} />

            <LemonField name="emits_signals">
                {({ value, onChange }) => (
                    <LemonCard hoverEffect={false} className="p-3">
                        <div className="flex items-center gap-4">
                            <HedgehogImTheDriver className="h-16 sm:h-20 w-auto shrink-0" />
                            <div className="flex-1 space-y-1">
                                <div className="text-sm font-medium">Self-driving</div>
                                <div className="text-xs text-muted">
                                    Don't just find problems, fix them. Issues this scanner spots flow into PostHog
                                    Signals, where agents dig into the root cause and draft a pull request. You stay in
                                    control of what ships.{' '}
                                    <Link to="https://posthog.com/self-driving" target="_blank">
                                        Learn more about PostHog self-driving
                                    </Link>
                                    .
                                </div>
                                {!isNew && <SelfDrivingOutcomesLine scannerId={scannerId} />}
                            </div>
                            <LemonSwitch
                                checked={!!value}
                                onChange={onChange}
                                label="Emit findings as Signals"
                                bordered
                                className="shrink-0"
                            />
                        </div>
                    </LemonCard>
                )}
            </LemonField>
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
    const { scanner, durationValidationError, hasUnsavedChanges } = useValues(replayScannerLogic({ id: scannerId }))
    const { searchParams } = useValues(router)
    const { discardScannerDraft } = useActions(replayScannerLogic({ id: scannerId }))
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [consentRequested, setConsentRequested] = useState(false)
    // The backend rejects scanner creation without org AI consent, so the popover interposes at
    // Save instead of letting the request 400.
    const needsConsent = isNew && !dataProcessingAccepted
    const stepIndex = SCANNER_EDITOR_STEPS.indexOf(step)
    const previous = stepIndex > 0 ? SCANNER_EDITOR_STEPS[stepIndex - 1] : null
    const prevStep = previous === 'template' && !isNew ? null : previous
    const nextStep = stepIndex < SCANNER_EDITOR_STEPS.length - 1 ? SCANNER_EDITOR_STEPS[stepIndex + 1] : null
    // A broken duration filter blocks the save, but only from the triggers step onward: gating an
    // earlier step's button on it blocks the wizard with a reason nothing on screen explains. RBAC
    // takes priority and must match the backend's create/update requirement exactly.
    const ownsDurationFilter = step === 'triggers' || step === 'budget'
    const durationError = ownsDurationFilter ? durationValidationError : null
    const saveDisabledReason = getReplayVisionEditDisabledReason(scanner?.user_access_level) ?? durationError
    // Editing one section from the goal overview: the edit is already in the form state, so the only
    // action needed is to return to the overview, where the whole draft is reviewed and created.
    const { from, ...overviewParams } = searchParams
    const fromOverview = from === 'overview'

    const cancel = (): void => {
        // Resetting first leaves nothing unsaved, so the leave guard can't prompt on top of this.
        discardScannerDraft()
        router.actions.push(isNew ? urls.replayVision() : urls.replayVision(scannerId))
    }
    const handleCancel = (): void => {
        if (!hasUnsavedChanges) {
            cancel()
            return
        }
        LemonDialog.open({
            title: isNew ? 'Discard this scanner?' : 'Discard your changes?',
            description: isNew
                ? "The scanner you've been setting up won't be saved."
                : "The changes you made won't be saved.",
            primaryButton: { children: 'Discard', status: 'danger', onClick: cancel },
            secondaryButton: { children: 'Keep editing' },
        })
    }

    return (
        <div className="flex flex-col gap-2">
            {/* The duration field lives on the recordings step, so budget needs the error spelled out. */}
            {step === 'budget' && durationError ? <div className="text-danger text-sm">{durationError}</div> : null}
            {fromOverview ? (
                <div className="flex flex-wrap items-center justify-end gap-2">
                    <LemonButton
                        type="tertiary"
                        onClick={handleCancel}
                        disabledReason={isSubmitting ? 'Saving…' : undefined}
                        data-attr="vision-editor-cancel"
                    >
                        Discard scanner
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        to={scannerStepUrlWithParams('overview', scannerId, overviewParams)}
                        disabledReason={saveDisabledReason ?? undefined}
                        data-attr="vision-editor-back-to-overview"
                    >
                        Back to overview
                    </LemonButton>
                </div>
            ) : (
                <div className="flex flex-wrap items-center justify-between gap-2">
                    {prevStep ? (
                        <LemonButton
                            type="tertiary"
                            to={scannerStepUrlWithParams(prevStep, scannerId, searchParams)}
                            data-attr="vision-editor-back"
                        >
                            Back
                        </LemonButton>
                    ) : null}
                    <div className="flex flex-wrap items-center gap-2 ml-auto">
                        <LemonButton
                            type="tertiary"
                            onClick={handleCancel}
                            disabledReason={isSubmitting ? 'Saving…' : undefined}
                            data-attr="vision-editor-cancel"
                        >
                            Cancel
                        </LemonButton>
                        {nextStep ? (
                            <LemonButton
                                type="primary"
                                loading={isSubmitting}
                                disabledReason={saveDisabledReason}
                                onClick={onAdvance}
                                data-attr="vision-editor-next"
                            >
                                Next: {STEP_LABELS[nextStep]}
                            </LemonButton>
                        ) : (
                            <AIConsentPopoverWrapper
                                placement="top-end"
                                showArrow
                                ignoreDismissal
                                hideTrainingDisclaimer
                                hidden={!consentRequested}
                                onApprove={() => {
                                    setConsentRequested(false)
                                    onSave()
                                }}
                                onDismiss={() => setConsentRequested(false)}
                            >
                                <LemonButton
                                    type="primary"
                                    loading={isSubmitting}
                                    disabledReason={saveDisabledReason}
                                    onClick={() => (needsConsent ? setConsentRequested(true) : onSave())}
                                    data-attr="vision-editor-save"
                                    data-ph-capture-attribute-scanner-type={scanner?.scanner_type}
                                >
                                    {needsConsent
                                        ? 'Allow AI analysis and create scanner'
                                        : isNew
                                          ? 'Create scanner'
                                          : 'Save changes'}
                                </LemonButton>
                            </AIConsentPopoverWrapper>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}

export default ScannerEditorSceneComponent
