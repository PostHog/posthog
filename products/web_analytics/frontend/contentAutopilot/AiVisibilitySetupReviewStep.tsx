import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { AiVisibilitySetupCostPanel } from './AiVisibilitySetupCostPanel'
import { aiVisibilitySetupReviewLogic } from './aiVisibilitySetupReviewLogic'
import { AiVisibilitySetupRunPanel } from './AiVisibilitySetupRunPanel'
import { AiVisibilitySetupWizardFooter } from './AiVisibilitySetupWizardFooter'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'
import { FREQUENCY_OPTIONS } from './engineFrequency'
import { openRestartSetupDialog } from './restartSetupDialog'
import { engineLabel } from './utils'

const SectionHeading = ({ title, detail }: { title: string; detail: string }): JSX.Element => (
    <div>
        <h4 className="m-0">{title}</h4>
        <p className="m-0 text-xs text-secondary">{detail}</p>
    </div>
)

export const AiVisibilitySetupReviewStep = (): JSX.Element => {
    const {
        prompts,
        keywordRows,
        loadedKeywords,
        engines,
        activePromptCount,
        promptsUpdating,
        keywordsUpdating,
        enginesUpdating,
    } = useValues(aiVisibilitySetupReviewLogic)
    const { togglePrompt, toggleKeyword, toggleEngine, setEngineFrequency, openAddPrompts } =
        useActions(aiVisibilitySetupReviewLogic)
    const { setupContext, restarting, runInProgress, jobRunning, job, hasCurrentChecks } =
        useValues(contentAutopilotSetupLogic)
    const stepPending = (name: string): boolean =>
        jobRunning && !!job && job.steps.some((step) => step.step === name && step.status !== 'done')
    const settingUp = stepPending('prompts')
    const pickingKeywords = stepPending('keywords')
    const { setWizardStep, startAgain } = useActions(contentAutopilotSetupLogic)
    const costEngines = (setupContext?.engines ?? [])
        .filter((engine) => engine.enabled && engine.available)
        .map(({ engine, frequency }) => ({ engine, frequency }))
    const keywordsOn = keywordRows.filter((row) => row.id !== null).length

    return (
        <div data-attr="ai-visibility-setup-review">
            <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
                <div className="flex min-w-0 flex-col gap-6">
                    <div>
                        <h3 className="m-0">Review what PostHog set up</h3>
                        <p className="m-0 mt-1 text-muted">
                            Turn off anything you don't want to track. Each engine that's on answers every prompt that's
                            on, on its schedule, and the keywords are counted in every answer.
                        </p>
                    </div>

                    <AiVisibilitySetupRunPanel />

                    <section className="flex flex-col gap-2" data-attr="ai-visibility-setup-review-engines">
                        <SectionHeading
                            title="Engines"
                            detail="More engines, and how many web searches each one runs per answer, are in settings."
                        />
                        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                            {engines.map((setting) => (
                                <div
                                    key={setting.engine}
                                    className="flex items-center gap-3 rounded border px-3 py-2"
                                    data-attr="ai-visibility-setup-review-engine"
                                >
                                    <span className="flex-1">
                                        <ContentAutopilotEngineLabel engine={setting.engine} />
                                    </span>
                                    <LemonSelect
                                        size="small"
                                        value={setting.frequency}
                                        options={FREQUENCY_OPTIONS}
                                        onChange={(frequency) =>
                                            frequency && setEngineFrequency(setting.engine, frequency)
                                        }
                                        disabledReason={
                                            setting.enabled ? undefined : 'Turn the engine on to choose how often'
                                        }
                                        data-attr="ai-visibility-setup-review-engine-frequency"
                                    />
                                    <LemonSwitch
                                        checked={setting.enabled}
                                        loading={!!enginesUpdating[setting.engine]}
                                        onChange={(enabled) => toggleEngine(setting.engine, enabled)}
                                        disabledReason={
                                            setting.available
                                                ? undefined
                                                : `${engineLabel(setting.engine)} isn't available yet`
                                        }
                                        aria-label={`Check prompts on ${engineLabel(setting.engine)}`}
                                    />
                                </div>
                            ))}
                        </div>
                    </section>

                    <section className="flex flex-col gap-2" data-attr="ai-visibility-setup-review-prompts">
                        <div className="flex flex-wrap items-end justify-between gap-2">
                            <SectionHeading
                                title={
                                    prompts?.length
                                        ? `Prompts: ${activePromptCount} of ${prompts.length} on`
                                        : 'Prompts'
                                }
                                detail="The questions the engines answer. Turn one off to stop checking it."
                            />
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlus />}
                                onClick={openAddPrompts}
                                disabledReason={
                                    runInProgress
                                        ? 'You can add your own prompts once setup and its first check finish'
                                        : undefined
                                }
                                data-attr="ai-visibility-setup-review-add-prompts"
                            >
                                Add my own prompts
                            </LemonButton>
                        </div>
                        {prompts && !(settingUp && prompts.length === 0) ? (
                            <ul className="m-0 flex list-none flex-col divide-y rounded border p-0">
                                {prompts.map((prompt) => (
                                    <li key={prompt.id} className="flex items-center gap-3 px-3 py-2">
                                        <LemonSwitch
                                            checked={prompt.active}
                                            loading={!!promptsUpdating[prompt.id]}
                                            onChange={(active) => togglePrompt(prompt.id, active)}
                                            aria-label={prompt.prompt}
                                            data-attr="ai-visibility-setup-review-prompt"
                                        />
                                        <span className={prompt.active ? 'flex-1' : 'flex-1 text-muted'}>
                                            {prompt.prompt}
                                        </span>
                                        {prompt.topic ? (
                                            <span className="shrink-0 text-xs text-secondary">{prompt.topic}</span>
                                        ) : null}
                                    </li>
                                ))}
                            </ul>
                        ) : settingUp ? (
                            <p className="m-0 text-muted">
                                PostHog is writing your prompts. They show here once saved.
                            </p>
                        ) : (
                            <LemonSkeleton className="h-40 w-full" />
                        )}
                    </section>

                    <section className="flex flex-col gap-2" data-attr="ai-visibility-setup-review-keywords">
                        <SectionHeading
                            title={
                                keywordRows.length ? `Keywords: ${keywordsOn} of ${keywordRows.length} on` : 'Keywords'
                            }
                            detail="Words and phrases counted in the prompts, the engines' searches and their answers. They don't add checks."
                        />
                        {loadedKeywords ? (
                            keywordRows.length > 0 ? (
                                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                                    {keywordRows.map((row) => (
                                        <LemonSwitch
                                            key={row.keyword}
                                            bordered
                                            fullWidth
                                            checked={row.id !== null}
                                            loading={!!keywordsUpdating[row.keyword]}
                                            onChange={(on) => toggleKeyword(row, on)}
                                            label={row.keyword}
                                            data-attr="ai-visibility-setup-review-keyword"
                                        />
                                    ))}
                                </div>
                            ) : (
                                <p className="m-0 text-muted">
                                    {pickingKeywords
                                        ? 'PostHog picks keywords after the prompts. They show here once saved.'
                                        : 'No keywords yet. You can add them on the Keywords tab.'}
                                </p>
                            )
                        ) : (
                            <LemonSkeleton className="h-16 w-full" />
                        )}
                    </section>

                    <section className="flex flex-col gap-1" data-attr="ai-visibility-setup-review-competitors">
                        <h4 className="m-0">Competitors</h4>
                        <p className="m-0 text-xs text-secondary">
                            {hasCurrentChecks
                                ? 'Choose your competitors in First results, from the brands the answers named.'
                                : 'Competitors appear once the first answers are in.'}
                        </p>
                    </section>
                </div>
                <div className="lg:sticky lg:top-4">
                    <AiVisibilitySetupCostPanel prompts={activePromptCount} engines={costEngines} />
                </div>
            </div>

            <AiVisibilitySetupWizardFooter
                backActions={
                    <LemonButton
                        type="secondary"
                        onClick={() => openRestartSetupDialog(setupContext, startAgain)}
                        loading={restarting}
                        data-attr="ai-visibility-setup-start-again"
                    >
                        Start again
                    </LemonButton>
                }
            >
                <LemonButton
                    type="primary"
                    onClick={() => setWizardStep('results')}
                    disabledReason={runInProgress ? 'Wait for the first check, or stop it' : undefined}
                    data-attr="ai-visibility-setup-next-results"
                >
                    Next
                </LemonButton>
            </AiVisibilitySetupWizardFooter>
        </div>
    )
}
