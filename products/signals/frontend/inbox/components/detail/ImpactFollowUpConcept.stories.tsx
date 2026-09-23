import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconCheckCircle, IconClock } from '@posthog/icons'

import { impactFollowUpExamples } from '../../__mocks__/impactFollowUpConceptMocks'
import type { FollowUpStage, ImpactFollowUpExample } from '../../__mocks__/impactFollowUpConceptMocks'
import { ImpactFollowUpConcept } from './ImpactFollowUpConcept'
import type { ImpactFollowUpConceptProps } from './ImpactFollowUpConcept'

const meta: Meta = {
    title: 'Scenes-App/Inbox/Impact follow-up concepts',
    parameters: { layout: 'fullscreen', viewMode: 'story' },
}
export default meta

type Story = StoryObj

function gallery(stage: FollowUpStage, version: ImpactFollowUpConceptProps['version']): JSX.Element {
    const names = {
        poster: '01 · Decision poster',
        queue: '02 · Inbox queue',
        tape: '03 · Daily tape',
        'poster-runway': '04 · Decision poster + runway',
    }
    return (
        <div className="min-h-screen bg-primary p-5">
            <div className={`mx-auto flex flex-col ${version === 'queue' ? 'max-w-7xl gap-2' : 'max-w-5xl gap-5'}`}>
                <div className="mb-3">
                    <h1 className="mb-1 text-xl font-semibold">
                        {names[version]} ·{' '}
                        {stage === 'planned'
                            ? 'Before release'
                            : stage === 'watching'
                              ? 'Watching'
                              : 'After the window'}
                    </h1>
                    <p className="m-0 text-sm text-secondary">
                        Five cases · invented data · controls are a preview only
                    </p>
                </div>
                {impactFollowUpExamples.map((example) => (
                    <ImpactFollowUpConcept key={example.id} example={example} stage={stage} version={version} />
                ))}
            </div>
        </div>
    )
}

export const AtAGlance: Story = {
    render: () => (
        <div className="min-h-screen bg-primary p-5">
            <div className="mx-auto flex max-w-7xl flex-col gap-2">
                <div className="mb-3">
                    <h1 className="mb-1 text-xl font-semibold">Impact at a glance · inbox queue</h1>
                    <p className="m-0 text-sm text-secondary">Early signs and final results · invented data</p>
                </div>
                {impactFollowUpExamples.map((example, index) => (
                    <ImpactFollowUpConcept
                        key={example.id}
                        example={example}
                        stage={index < 2 ? 'finished' : 'watching'}
                        version="queue"
                    />
                ))}
            </div>
        </div>
    ),
}

export const PosterBeforeRelease: Story = { render: () => gallery('planned', 'poster') }
export const PosterWatching: Story = { render: () => gallery('watching', 'poster') }
export const PosterAfterWindow: Story = { render: () => gallery('finished', 'poster') }

export const QueueBeforeRelease: Story = { render: () => gallery('planned', 'queue') }
export const QueueWatching: Story = { render: () => gallery('watching', 'queue') }
export const QueueAfterWindow: Story = { render: () => gallery('finished', 'queue') }

export const TapeBeforeRelease: Story = { render: () => gallery('planned', 'tape') }
export const TapeWatching: Story = { render: () => gallery('watching', 'tape') }
export const TapeAfterWindow: Story = { render: () => gallery('finished', 'tape') }

export const PosterRunwayBeforeRelease: Story = { render: () => gallery('planned', 'poster-runway') }
export const PosterRunwayWatching: Story = { render: () => gallery('watching', 'poster-runway') }
export const PosterRunwayAfterWindow: Story = { render: () => gallery('finished', 'poster-runway') }

type InboxFilter = 'All' | 'Needs work' | 'Monitoring' | 'Resolved'

function MonitoringProgress({ example, small = false, finished = false }: {
    example: ImpactFollowUpExample
    small?: boolean
    finished?: boolean
}): JSX.Element {
    const elapsed = finished ? example.windowDays : example.elapsedDays
    const observed = finished ? example.finishedSample : example.watchingSample
    const time = Math.min(100, (elapsed / example.windowDays) * 100)
    const sample = Math.min(100, (observed / example.sampleNeeded) * 100)

    return (
        <div className={`grid gap-2 ${small ? 'min-w-40' : ''}`}>
            {[
                { label: 'Time', value: `${elapsed} / ${example.windowDays} days`, percent: time },
                {
                    label: example.sampleLabel,
                    value: `${observed} / ${example.sampleNeeded}`,
                    percent: sample,
                },
            ].map(({ label, value, percent }) => (
                <div key={label}>
                    <div className="mb-1 flex justify-between gap-2 text-xs">
                        <span className="truncate text-secondary">{label}</span>
                        <strong className="whitespace-nowrap">{value}</strong>
                    </div>
                    <div
                        role="progressbar"
                        aria-label={`${label}: ${value}`}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={Math.round(percent)}
                        className="h-1.5 overflow-hidden rounded-full bg-fill-primary"
                    >
                        <div className="h-full rounded-full bg-accent" style={{ width: `${percent}%` }} />
                    </div>
                </div>
            ))}
        </div>
    )
}

function MonitoringBadge({ children }: { children: string }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-primary bg-surface-secondary px-2 py-0.5 text-xs font-medium">
            {children === 'Resolved' ? <IconCheckCircle className="size-3.5" /> : <IconClock className="size-3.5" />}
            {children}
        </span>
    )
}

function FullReportContext({ initialExample = impactFollowUpExamples[0], stage = 'watching', onBack }: {
    initialExample?: ImpactFollowUpExample
    stage?: 'watching' | 'finished'
    onBack?: () => void
}): JSX.Element {
    const [selectedId, setSelectedId] = useState(initialExample.id)
    const example = impactFollowUpExamples.find((item) => item.id === selectedId) ?? initialExample
    const displayExample = stage === 'finished' ? { ...example, decisionDate: 'Sep 22' } : example
    const completed = stage === 'finished' && example.verdict === 'met'
    const status = completed ? 'Resolved' : 'Monitoring'
    const nextStep = example.watchingSignal === 'no_trial'
        ? 'Wait for a qualifying use of this feature.'
        : example.watchingSignal === 'missing_signal'
          ? 'Check why a required signal is missing.'
          : `Check again on ${example.decisionDate}.`

    return (
        <div className="min-h-screen bg-surface-secondary">
            <div className="border-b border-primary bg-surface-primary px-5 py-3 text-sm">
                <div className="mx-auto flex max-w-6xl items-center gap-2 text-secondary">
                    {onBack ? (
                        <button type="button" className="flex items-center gap-1 hover:text-primary" onClick={onBack}>
                            <IconArrowLeft className="size-4" /> Inbox
                        </button>
                    ) : (
                        <span>Self-driving / Inbox</span>
                    )}
                    <span>/</span><span className="text-primary">Report</span>
                    <span className="ml-auto text-xs">Storybook preview · invented data</span>
                </div>
            </div>
            <div className="mx-auto max-w-6xl px-5 py-6">
                <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <div className="mb-2 flex items-center gap-2">
                            <MonitoringBadge>{status}</MonitoringBadge>
                            <span className="text-xs text-secondary">Product quality · high priority</span>
                        </div>
                        <h1 className="m-0 text-2xl font-semibold">{example.title}</h1>
                        <p className="mb-0 mt-1 text-secondary">{example.outcome}</p>
                    </div>
                    <label className="flex items-center gap-2 text-xs text-secondary">
                        Preview another case
                        <select
                            aria-label="Preview another report"
                            value={selectedId}
                            onChange={(event) => setSelectedId(event.target.value)}
                            className="max-w-48 rounded border border-primary bg-surface-primary px-2 py-1.5 text-primary"
                        >
                            {impactFollowUpExamples.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
                        </select>
                    </label>
                </div>
                <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_16rem]">
                    <main className="flex min-w-0 flex-col gap-5">
                        <section className="rounded border border-primary bg-surface-primary p-5">
                            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-secondary">The report</div>
                            <h2 className="m-0 text-lg font-semibold">What needs to change?</h2>
                            <p className="mb-0 mt-2 text-sm">{example.goal}</p>
                            <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 border-t border-primary pt-3 text-sm">
                                <span><strong>Before:</strong> {example.baseline}</span>
                                <span><strong>Fix:</strong> merged PR · release confirmed</span>
                            </div>
                        </section>
                        <section aria-label="Expected impact">
                            <div className="mb-2 flex items-baseline justify-between gap-3">
                                <h2 className="m-0 text-base font-semibold">Expected impact</h2>
                                <span className="text-xs text-secondary">Measured after release</span>
                            </div>
                            <ImpactFollowUpConcept example={displayExample} stage={stage} version="poster-runway" />
                        </section>
                    </main>
                    <aside className="flex flex-col gap-4 text-sm">
                        <section className="rounded border border-primary bg-surface-primary p-4">
                            <h2 className="m-0 text-sm font-semibold">From report to result</h2>
                            <ol className="mb-0 mt-4 flex flex-col gap-3 pl-0 text-xs">
                                {['Ready', 'In progress', 'Monitoring', 'Resolved'].map((step, index) => (
                                    <li key={step} className="flex items-center gap-2">
                                        <span className={`flex size-5 shrink-0 items-center justify-center rounded-full ${index < 2 || completed ? 'bg-success-highlight text-success' : index === 2 ? 'bg-fill-primary font-bold text-primary' : 'border border-primary text-secondary'}`}>
                                            {index < 2 || completed ? '✓' : index + 1}
                                        </span>
                                        <span className={step === status ? 'font-semibold' : 'text-secondary'}>{step}</span>
                                    </li>
                                ))}
                            </ol>
                        </section>
                        <section className="rounded border border-primary bg-surface-primary p-4">
                            <h2 className="m-0 text-sm font-semibold">{stage === 'finished' ? 'What did we learn?' : 'When will we know?'}</h2>
                            <p className="my-2 text-xs text-secondary">
                                {stage === 'finished' ? `${example.windowDays}-day check complete` : `Decision target: ${example.decisionDate}`}
                            </p>
                            <MonitoringProgress example={example} finished={stage === 'finished'} />
                            <p className="mb-0 mt-3 text-xs">
                                {stage === 'finished' ? example.resultNote : nextStep}
                            </p>
                            {stage === 'finished' && !completed && (
                                <p className="mb-0 mt-2 text-xs font-medium">Next: {example.nextStep}</p>
                            )}
                        </section>
                        <section className="rounded border border-primary bg-surface-primary p-4 text-xs">
                            <h2 className="m-0 text-sm font-semibold">Work history</h2>
                            <div className="mt-3 flex justify-between"><span>Report created</span><span>Done</span></div>
                            <div className="mt-2 flex justify-between"><span>PR merged</span><span>Done</span></div>
                            <div className="mt-2 flex justify-between"><span>Impact check</span><span>{completed ? 'Done' : stage === 'finished' ? 'Needs follow-up' : status}</span></div>
                        </section>
                    </aside>
                </div>
            </div>
        </div>
    )
}

function InboxContext(): JSX.Element {
    const [filter, setFilter] = useState<InboxFilter>('All')
    const [selected, setSelected] = useState<ImpactFollowUpExample | null>(null)
    if (selected) {
        return <FullReportContext key={selected.id} initialExample={selected} onBack={() => setSelected(null)} />
    }

    const showWork = filter === 'All' || filter === 'Needs work'
    const showMonitoring = filter === 'All' || filter === 'Monitoring'
    const showResolved = filter === 'All' || filter === 'Resolved'

    return (
        <div className="min-h-screen bg-surface-secondary">
            <div className="border-b border-primary bg-surface-primary px-6 py-4">
                <div className="mx-auto max-w-5xl">
                    <div className="text-xs text-secondary">Self-driving</div>
                    <h1 className="m-0 text-2xl font-semibold">Inbox</h1>
                    <p className="mb-0 mt-1 text-sm text-secondary">Work to review, then changes to watch.</p>
                </div>
            </div>
            <div className="mx-auto max-w-5xl px-6 py-5">
                <div className="mb-5 flex flex-wrap gap-2" aria-label="Filter reports">
                    {(['All', 'Needs work', 'Monitoring', 'Resolved'] as const).map((name) => (
                        <button
                            key={name}
                            type="button"
                            aria-pressed={filter === name}
                            onClick={() => setFilter(name)}
                            className={`rounded px-3 py-1.5 text-sm ${filter === name ? 'bg-fill-primary font-semibold' : 'border border-primary bg-surface-primary'}`}
                        >
                            {name} <span className="ml-1 opacity-70">{name === 'All' ? 7 : name === 'Monitoring' ? 5 : 1}</span>
                        </button>
                    ))}
                    <span className="ml-auto self-center text-xs text-secondary">Storybook preview · invented data</span>
                </div>
                <div className="flex flex-col gap-2">
                    {showWork && (
                        <article className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded border border-primary bg-surface-primary p-4 text-sm">
                            <span className="min-w-0 flex-1"><strong>Review the proposed release note</strong><br /><span className="text-xs text-secondary">Needs your decision before work starts</span></span>
                            <span className="rounded border border-primary px-2 py-1 text-xs">Ready</span>
                            <IconArrowRight className="size-4 text-secondary" />
                        </article>
                    )}
                    {showMonitoring && impactFollowUpExamples.map((example) => {
                        const signal = example.watchingSignal
                        const headline = signal === 'promising' ? 'Looks good so far' : signal === 'risk' ? 'Still happening' : 'Not enough proof'
                        const secondary = signal === 'no_trial'
                            ? 'No qualifying use yet'
                            : signal === 'missing_signal'
                              ? 'A required signal is missing'
                              : `${example.watchingValue} now · goal ${example.goalShort}`
                        return (
                            <button
                                type="button"
                                key={example.id}
                                onClick={() => setSelected(example)}
                                className="w-full rounded border border-primary bg-surface-primary p-4 text-left hover:border-secondary focus-visible:outline focus-visible:outline-2"
                                aria-label={`Open ${example.title}, Monitoring: ${headline}`}
                            >
                                <div className="grid items-center gap-3 md:grid-cols-[minmax(0,1.4fr)_minmax(9rem,0.9fr)_minmax(10rem,1fr)_auto]">
                                    <div className="min-w-0">
                                        <div className="mb-1 flex items-center gap-2"><MonitoringBadge>Monitoring</MonitoringBadge><span className="text-xs text-secondary">Decision {example.decisionDate}</span></div>
                                        <strong className="block truncate text-sm">{example.title}</strong>
                                        <span className="block truncate text-xs text-secondary">{example.outcome}</span>
                                    </div>
                                    <div className={`text-base font-semibold ${signal === 'risk' ? 'text-danger' : signal === 'promising' ? 'text-success' : 'text-primary'}`}>
                                        {headline}
                                        <div className="text-xs font-normal text-secondary">{secondary}</div>
                                    </div>
                                    <MonitoringProgress example={example} small />
                                    <IconArrowRight className="hidden size-4 text-secondary md:block" />
                                </div>
                            </button>
                        )
                    })}
                    {showResolved && (
                        <article className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded border border-primary bg-surface-primary p-4 text-sm">
                            <span className="min-w-0 flex-1"><strong>Keep the export preview available</strong><br /><span className="text-xs text-secondary">Goal met after release · check complete</span></span>
                            <span className="flex items-center gap-1 text-xs text-success"><IconCheckCircle className="size-4" /> Worked · Resolved</span>
                        </article>
                    )}
                </div>
                <p className="mt-4 text-xs text-secondary">Monitoring means a change shipped; it does not mean that it worked. Open a row to see its evidence.</p>
            </div>
        </div>
    )
}

export const FullReportMonitoring: Story = { render: () => <FullReportContext /> }
export const FullReportAfterWindow: Story = { render: () => <FullReportContext stage="finished" /> }
export const InboxWithMonitoring: Story = { render: () => <InboxContext /> }
