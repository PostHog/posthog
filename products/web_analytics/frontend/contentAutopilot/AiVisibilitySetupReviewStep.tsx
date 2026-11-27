import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import {
    Button,
    Heading,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Switch,
    Text,
} from '@posthog/quill'

import type { CheckFrequencyEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilitySetupCostPanel } from './AiVisibilitySetupCostPanel'
import { aiVisibilitySetupReviewLogic } from './aiVisibilitySetupReviewLogic'
import { AiVisibilitySetupRunPanel } from './AiVisibilitySetupRunPanel'
import { AiVisibilitySetupWizardFooter } from './AiVisibilitySetupWizardFooter'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'
import { FREQUENCY_OPTIONS, frequencyLabel } from './engineFrequency'
import { engineLabel } from './utils'

const SectionHeading = ({ title, detail }: { title: string; detail: string }): JSX.Element => (
    <div>
        <Heading size="sm" render={<h4 className="m-0" />}>
            {title}
        </Heading>
        <Text size="xs" variant="muted" render={<p className="m-0" />}>
            {detail}
        </Text>
    </div>
)

export const AiVisibilitySetupReviewStep = ({ onStartAgain }: { onStartAgain: () => void }): JSX.Element => {
    const {
        prompts,
        keywordRows,
        loadedKeywords,
        engines,
        activePromptCount,
        promptsUpdating,
        keywordsUpdating,
        enginesUpdating,
        promptsFailed,
        keywordsFailed,
    } = useValues(aiVisibilitySetupReviewLogic)
    const { togglePrompt, toggleKeyword, toggleEngine, setEngineFrequency, openAddPrompts, loadPrompts, loadKeywords } =
        useActions(aiVisibilitySetupReviewLogic)
    const { setupContext, restarting, runInProgress, jobRunning, job } = useValues(contentAutopilotSetupLogic)
    const stepPending = (name: string): boolean =>
        jobRunning && !!job && job.steps.some((step) => step.step === name && step.status !== 'done')
    const settingUp = stepPending('prompts')
    const pickingKeywords = stepPending('keywords')
    const { setWizardStep } = useActions(contentAutopilotSetupLogic)
    const costEngines = (setupContext?.engines ?? [])
        .filter((engine) => engine.enabled && engine.available)
        .map(({ engine, frequency }) => ({ engine, frequency }))
    const keywordsOn = keywordRows.filter((row) => row.id !== null).length

    return (
        <div data-attr="ai-visibility-setup-review">
            <div className="flex flex-col items-start gap-6 lg:flex-row">
                <div className="flex w-full min-w-0 flex-1 flex-col gap-6">
                    <div>
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Review what PostHog set up
                        </Heading>
                        <Text size="sm" variant="muted" render={<p className="m-0 mt-1" />}>
                            Turn off anything you don't want to track. Each engine that's on answers every prompt that's
                            on, on its schedule, and the keywords are counted in every answer.
                        </Text>
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
                                    className="flex items-center gap-3 rounded-md border px-3 py-2"
                                    data-attr="ai-visibility-setup-review-engine"
                                >
                                    <span className="flex-1">
                                        <ContentAutopilotEngineLabel engine={setting.engine} />
                                    </span>
                                    <Select<CheckFrequencyEnumApi>
                                        value={setting.frequency}
                                        onValueChange={(frequency) =>
                                            frequency && setEngineFrequency(setting.engine, frequency)
                                        }
                                    >
                                        <SelectTrigger
                                            size="sm"
                                            aria-label={`How often ${engineLabel(setting.engine)} checks`}
                                            disabledReason={
                                                !setting.enabled
                                                    ? 'Turn the engine on to choose how often'
                                                    : enginesUpdating[setting.engine]
                                                      ? 'Saving…'
                                                      : undefined
                                            }
                                            data-attr="ai-visibility-setup-review-engine-frequency"
                                        >
                                            <SelectValue>
                                                {(value: CheckFrequencyEnumApi | null) =>
                                                    value && frequencyLabel(value)
                                                }
                                            </SelectValue>
                                        </SelectTrigger>
                                        <SelectContent>
                                            {FREQUENCY_OPTIONS.map((option) => (
                                                <SelectItem key={option.value} value={option.value}>
                                                    {option.label}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                    <Switch
                                        checked={setting.enabled}
                                        onCheckedChange={(enabled) => toggleEngine(setting.engine, enabled)}
                                        disabledReason={
                                            !setting.available
                                                ? `${engineLabel(setting.engine)} isn't available yet`
                                                : enginesUpdating[setting.engine]
                                                  ? 'Saving…'
                                                  : undefined
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
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={openAddPrompts}
                                disabledReason={
                                    runInProgress
                                        ? 'You can add your own prompts once setup and its first check finish'
                                        : undefined
                                }
                                data-attr="ai-visibility-setup-review-add-prompts"
                            >
                                <IconPlus />
                                Add my own prompts
                            </Button>
                        </div>
                        {prompts && !(settingUp && prompts.length === 0) ? (
                            <ul className="m-0 flex list-none flex-col divide-y rounded-md border p-0">
                                {prompts.map((prompt) => (
                                    <li key={prompt.id} className="flex items-center gap-3 px-3 py-2">
                                        <Switch
                                            checked={prompt.active}
                                            onCheckedChange={(active) => togglePrompt(prompt.id, active)}
                                            disabledReason={promptsUpdating[prompt.id] ? 'Saving…' : undefined}
                                            aria-label={prompt.prompt}
                                            data-attr="ai-visibility-setup-review-prompt"
                                        />
                                        <span className={prompt.active ? 'flex-1' : 'flex-1 text-muted-foreground'}>
                                            {prompt.prompt}
                                        </span>
                                        {prompt.topic ? (
                                            <Text size="xs" variant="muted" render={<span className="shrink-0" />}>
                                                {prompt.topic}
                                            </Text>
                                        ) : null}
                                    </li>
                                ))}
                            </ul>
                        ) : settingUp ? (
                            <Text size="sm" variant="muted" render={<p className="m-0" />}>
                                PostHog is writing your prompts. They show here once saved.
                            </Text>
                        ) : promptsFailed ? (
                            <AiVisibilityBanner type="error" action={{ children: 'Try again', onClick: loadPrompts }}>
                                Your prompts didn't load.
                            </AiVisibilityBanner>
                        ) : (
                            <Skeleton className="h-40 w-full" />
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
                                        <div key={row.keyword} className="rounded-md border px-3 py-2">
                                            <Switch
                                                checked={row.id !== null}
                                                onCheckedChange={(on) => toggleKeyword(row, on)}
                                                disabledReason={keywordsUpdating[row.keyword] ? 'Saving…' : undefined}
                                                data-attr="ai-visibility-setup-review-keyword"
                                            >
                                                {row.keyword}
                                            </Switch>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <Text size="sm" variant="muted" render={<p className="m-0" />}>
                                    {pickingKeywords
                                        ? 'PostHog picks keywords after the prompts. They show here once saved.'
                                        : 'No keywords yet. You can add them on the Keywords tab.'}
                                </Text>
                            )
                        ) : keywordsFailed ? (
                            <AiVisibilityBanner type="error" action={{ children: 'Try again', onClick: loadKeywords }}>
                                Your keywords didn't load.
                            </AiVisibilityBanner>
                        ) : (
                            <Skeleton className="h-16 w-full" />
                        )}
                    </section>
                </div>
                <div className="w-full shrink-0 lg:sticky lg:top-4 lg:w-80">
                    <AiVisibilitySetupCostPanel prompts={activePromptCount} engines={costEngines} />
                </div>
            </div>

            <AiVisibilitySetupWizardFooter
                backActions={
                    <Button
                        variant="outline"
                        onClick={onStartAgain}
                        loading={restarting}
                        data-attr="ai-visibility-setup-start-again"
                    >
                        Start again
                    </Button>
                }
            >
                <Button
                    variant="primary"
                    onClick={() => setWizardStep('results')}
                    disabledReason={runInProgress ? 'Wait for the first check, or stop it' : undefined}
                    data-attr="ai-visibility-setup-next-results"
                >
                    Next
                </Button>
            </AiVisibilitySetupWizardFooter>
        </div>
    )
}
