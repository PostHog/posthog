import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconBook, IconCheckCircle, IconChevronDown, IconCopy, IconMagicWand, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { humanFriendlyDuration } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'

import { SetupCheck, WizardStep, sourceMapsFixWizardLogic } from './sourceMapsFixWizardLogic'
import { SOURCE_MAPS_TECHNOLOGIES, Technology } from './sourceMapsTechnologies'

const STEPS: { step: WizardStep; label: string }[] = [
    { step: 1, label: 'Technology' },
    { step: 2, label: 'Configure' },
    { step: 3, label: 'Prompt' },
    { step: 4, label: 'Verify' },
]

export function SourceMapsFixModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    const { currentStep } = useValues(sourceMapsFixWizardLogic)
    const { nextStep, prevStep, reset } = useActions(sourceMapsFixWizardLogic)

    useEffect(() => {
        if (isOpen) {
            reset()
        }
    }, [isOpen, reset])

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Fix missing source maps with AI"
            description="Pick your stack, hand your agent the prompt, drop one secret into CI, then verify the build is landing."
            width={720}
            footer={
                <>
                    <LemonButton type="tertiary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <div className="flex-1" />
                    {currentStep > 1 && (
                        <LemonButton type="secondary" onClick={prevStep}>
                            Back
                        </LemonButton>
                    )}
                    {currentStep < 4 ? (
                        <LemonButton type="primary" onClick={nextStep}>
                            Next
                        </LemonButton>
                    ) : (
                        <LemonButton type="primary" onClick={onClose}>
                            Done
                        </LemonButton>
                    )}
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <Stepper currentStep={currentStep} />
                <div className="min-h-[380px]">
                    {currentStep === 1 && <Step1Technology />}
                    {currentStep === 2 && <Step2Configure />}
                    {currentStep === 3 && <Step3Prompt />}
                    {currentStep === 4 && <Step4Verify />}
                </div>
            </div>
        </LemonModal>
    )
}

function Stepper({ currentStep }: { currentStep: WizardStep }): JSX.Element {
    const { setStep } = useActions(sourceMapsFixWizardLogic)

    return (
        <nav className="flex items-center justify-center" aria-label="Source maps setup progress">
            {STEPS.map(({ step, label }, index) => {
                const isCompleted = currentStep > step
                const isCurrent = currentStep === step
                const isFuture = step > currentStep
                return (
                    <div key={step} className="flex items-center">
                        {index > 0 && (
                            <div
                                className={cn(
                                    'w-8 h-px transition-colors duration-150',
                                    currentStep >= step ? 'bg-success' : 'bg-border-primary'
                                )}
                            />
                        )}
                        <button
                            type="button"
                            onClick={() => setStep(step)}
                            disabled={isFuture}
                            className={cn(
                                'group flex items-center gap-1.5 px-2 py-1 rounded transition-all duration-150',
                                'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                                isFuture
                                    ? 'opacity-50 cursor-not-allowed'
                                    : 'hover:bg-fill-button-tertiary-hover active:scale-[0.98]'
                            )}
                            aria-current={isCurrent ? 'step' : undefined}
                        >
                            {isCompleted ? (
                                <IconCheckCircle className="size-5 text-success" />
                            ) : (
                                <span
                                    className={cn(
                                        'flex items-center justify-center size-5 rounded-full text-xs font-semibold transition-all duration-150',
                                        isCurrent && 'bg-accent text-primary-inverse ring-2 ring-accent/25',
                                        !isCurrent && 'bg-surface-secondary text-secondary border border-primary'
                                    )}
                                >
                                    {step}
                                </span>
                            )}
                            <span
                                className={cn(
                                    'text-sm transition-colors duration-150',
                                    isCurrent && 'font-semibold text-primary',
                                    isCompleted && 'font-medium text-primary',
                                    !isCompleted && !isCurrent && 'text-secondary'
                                )}
                            >
                                {label}
                            </span>
                        </button>
                    </div>
                )
            })}
        </nav>
    )
}

function Step1Technology(): JSX.Element {
    const { selectedTechKey } = useValues(sourceMapsFixWizardLogic)
    const { setSelectedTechKey } = useActions(sourceMapsFixWizardLogic)

    return (
        <div className="flex flex-col gap-3">
            <p className="text-sm text-secondary m-0">
                Pick your stack. <span className="font-medium text-default">Auto detect</span> is a great default — the
                agent will read your project and pick the right integration.
            </p>
            <div className="grid grid-cols-3 gap-2">
                {SOURCE_MAPS_TECHNOLOGIES.map((tech) => (
                    <TechnologyCard
                        key={tech.key}
                        technology={tech}
                        selected={selectedTechKey === tech.key}
                        onClick={() => setSelectedTechKey(tech.key)}
                    />
                ))}
            </div>
        </div>
    )
}

function TechnologyCard({
    technology,
    selected,
    onClick,
}: {
    technology: Technology
    selected: boolean
    onClick: () => void
}): JSX.Element {
    const isAuto = technology.key === 'auto'
    return (
        <button
            type="button"
            onClick={onClick}
            className={cn(
                'flex flex-col items-center justify-center gap-2 p-3 rounded-md border-2 transition-colors',
                'bg-surface-primary hover:bg-surface-secondary',
                selected ? 'border-accent' : 'border-border-primary'
            )}
            aria-pressed={selected}
        >
            <div className="size-8 flex items-center justify-center">
                {technology.image ? (
                    <img src={technology.image} alt={`${technology.name} logo`} className="size-8" />
                ) : isAuto ? (
                    <IconMagicWand className="size-7 text-accent" />
                ) : (
                    <span className="size-8 rounded bg-surface-secondary flex items-center justify-center text-xs font-semibold text-secondary">
                        {technology.name.slice(0, 2)}
                    </span>
                )}
            </div>
            <span className="text-sm font-medium text-default">{technology.name}</span>
        </button>
    )
}

function Step3Prompt(): JSX.Element {
    const { prompt, selectedTechnology, promptRevealed } = useValues(sourceMapsFixWizardLogic)
    const { setPromptRevealed } = useActions(sourceMapsFixWizardLogic)

    return (
        <div className="flex flex-col gap-4">
            <p className="text-sm text-secondary m-0">
                Paste this into your coding agent — it has everything it needs to set up{' '}
                <span className="font-medium text-default">{selectedTechnology.name}</span>.
            </p>
            <div className="flex items-stretch gap-2">
                <LemonButton
                    type="primary"
                    icon={<IconCopy />}
                    size="large"
                    onClick={() => copyToClipboard(prompt, 'prompt')}
                    fullWidth
                    center
                >
                    Copy prompt
                </LemonButton>
                <LemonButton
                    type="secondary"
                    icon={<IconBook />}
                    size="large"
                    to={selectedTechnology.docsLink}
                    targetBlank
                >
                    Docs
                </LemonButton>
            </div>
            <button
                type="button"
                onClick={() => setPromptRevealed(!promptRevealed)}
                className="flex items-center justify-center gap-1 text-xs text-secondary hover:text-primary bg-transparent border-0 p-0 cursor-pointer"
            >
                <IconChevronDown className={cn('size-3 transition-transform', promptRevealed && 'rotate-180')} />
                {promptRevealed ? 'Hide prompt' : 'Show prompt'}
            </button>
            {promptRevealed && (
                <pre className="text-xs bg-surface-secondary border rounded-md p-3 whitespace-pre-wrap font-mono max-h-72 overflow-y-auto m-0">
                    {prompt}
                </pre>
            )}
        </div>
    )
}

function Step2Configure(): JSX.Element {
    const { projectId, selectedTechnology, createdApiKey, isCreatingApiKey, apiKeyError } =
        useValues(sourceMapsFixWizardLogic)
    const { createApiKey } = useActions(sourceMapsFixWizardLogic)
    const { envVars } = selectedTechnology

    const apiKeyValue = createdApiKey?.value ?? '<your-api-key-or-press-generate>'
    const envContent = `${envVars.apiKey}=${apiKeyValue}\n${envVars.projectId}=${projectId}`

    return (
        <div className="flex flex-col gap-3">
            <p className="text-sm text-secondary m-0">
                Make sure your local and CI build processes have access to these env variables.
            </p>
            <div className="rounded-md border border-primary bg-surface-primary overflow-hidden">
                <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-primary bg-surface-secondary">
                    <div className="text-xs font-mono text-secondary">.env</div>
                    <div className="flex items-center gap-1">
                        {!createdApiKey?.value && (
                            <LemonButton
                                size="small"
                                type="primary"
                                icon={isCreatingApiKey ? <Spinner /> : <IconMagicWand />}
                                disabled={isCreatingApiKey}
                                onClick={createApiKey}
                            >
                                {isCreatingApiKey ? 'Creating…' : 'Generate API key'}
                            </LemonButton>
                        )}
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconCopy />}
                            onClick={() => copyToClipboard(envContent, '.env contents')}
                        />
                    </div>
                </div>
                <pre
                    className={cn(
                        'text-xs font-mono p-3 m-0 whitespace-pre-wrap',
                        createdApiKey?.value && 'ph-no-capture'
                    )}
                >
                    {envContent}
                </pre>
            </div>
            {createdApiKey?.value && (
                <div className="flex items-center gap-1 text-xs text-success">
                    <IconCheckCircle className="size-4" />
                    Key created — copy these now, the key won't be shown again.
                </div>
            )}
            {apiKeyError && <div className="text-xs text-danger">{apiKeyError}</div>}
        </div>
    )
}

function Step4Verify(): JSX.Element {
    const { setupCheck, setupCheckLoading } = useValues(sourceMapsFixWizardLogic)
    const { loadSetupCheck } = useActions(sourceMapsFixWizardLogic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-start justify-between gap-2">
                <p className="text-sm text-secondary m-0">
                    Once CI runs a build, you'll see uploads and frame activity land here. Showing the last 15 minutes.
                </p>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={setupCheckLoading ? <Spinner /> : <IconRefresh />}
                    onClick={loadSetupCheck}
                    disabled={setupCheckLoading}
                >
                    Refresh
                </LemonButton>
            </div>

            <VerifySymbolSets data={setupCheck} loading={setupCheckLoading} />
            <VerifyFrames data={setupCheck} loading={setupCheckLoading} />
        </div>
    )
}

function VerifySymbolSets({ data, loading }: { data: SetupCheck | null; loading: boolean }): JSX.Element {
    const symbolSets = data?.symbol_sets ?? []
    return (
        <section className="rounded-md border border-primary bg-surface-primary">
            <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-primary">
                <div className="flex flex-col">
                    <div className="text-sm font-semibold">Symbol set uploads</div>
                    <div className="text-xs text-secondary">Source map files received from your build.</div>
                </div>
                <div
                    className={cn(
                        'text-xs font-semibold px-2 py-0.5 rounded-full',
                        symbolSets.length > 0
                            ? 'bg-success-highlight text-success'
                            : 'bg-surface-secondary text-secondary'
                    )}
                >
                    {symbolSets.length}
                </div>
            </div>
            {loading && !data ? (
                <div className="p-4 flex items-center justify-center text-xs text-secondary gap-2">
                    <Spinner /> Checking…
                </div>
            ) : symbolSets.length === 0 ? (
                <div className="p-4 text-xs text-secondary text-center">
                    Nothing yet. Run a build in CI and refresh — uploads usually show up within a minute.
                </div>
            ) : (
                <ul className="m-0 p-0 list-none divide-y divide-border-primary">
                    {symbolSets.map((ss) => (
                        <li key={ss.id} className="flex items-center justify-between gap-2 px-3 py-2">
                            <div className="flex items-center gap-2 min-w-0">
                                {ss.has_uploaded_file ? (
                                    <IconCheckCircle className="size-4 text-success shrink-0" />
                                ) : (
                                    <span className="size-2 rounded-full bg-warning shrink-0" />
                                )}
                                <code className="text-xs font-mono truncate">{ss.ref}</code>
                            </div>
                            <span className="text-xs text-secondary shrink-0">{relativeAgo(ss.created_at)}</span>
                        </li>
                    ))}
                </ul>
            )}
        </section>
    )
}

function VerifyFrames({ data, loading }: { data: SetupCheck | null; loading: boolean }): JSX.Element {
    const frames = data?.frames
    const total = frames?.total ?? 0
    const resolved = frames?.resolved ?? 0
    const unresolved = frames?.unresolved ?? 0
    const resolvedPct = total > 0 ? Math.round((resolved / total) * 100) : 0
    const healthy = total > 0 && resolvedPct >= 90

    return (
        <section className="rounded-md border border-primary bg-surface-primary">
            <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-primary">
                <div className="flex flex-col">
                    <div className="text-sm font-semibold">JavaScript frame resolution</div>
                    <div className="text-xs text-secondary">How many recent JS frames mapped back to your source.</div>
                </div>
                {total > 0 && (
                    <div
                        className={cn(
                            'text-xs font-semibold px-2 py-0.5 rounded-full',
                            healthy ? 'bg-success-highlight text-success' : 'bg-warning-highlight text-warning'
                        )}
                    >
                        {resolvedPct}%
                    </div>
                )}
            </div>
            {loading && !data ? (
                <div className="p-4 flex items-center justify-center text-xs text-secondary gap-2">
                    <Spinner /> Checking…
                </div>
            ) : total === 0 ? (
                <div className="p-4 text-xs text-secondary text-center">
                    No JS frames in the last 15 minutes. Trigger a JS error in your app to see resolution stats.
                </div>
            ) : (
                <div className="p-3 flex flex-col gap-2">
                    <div className="w-full h-2 bg-surface-secondary rounded-full overflow-hidden flex">
                        <div
                            className="h-2 bg-success"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: `${resolvedPct}%` }}
                        />
                        <div className="flex-1 h-2 bg-warning" />
                    </div>
                    <div className="flex items-center justify-between text-xs text-secondary">
                        <span>
                            <span className="font-semibold text-default">{resolved.toLocaleString()}</span> resolved
                        </span>
                        <span>
                            <span className="font-semibold text-default">{unresolved.toLocaleString()}</span> unresolved
                        </span>
                        <span>
                            <span className="font-semibold text-default">{total.toLocaleString()}</span> total
                        </span>
                    </div>
                </div>
            )}
        </section>
    )
}

function relativeAgo(iso: string): string {
    const secs = (Date.now() - new Date(iso).getTime()) / 1000
    if (secs < 60) {
        return 'just now'
    }
    return `${humanFriendlyDuration(secs)} ago`
}
