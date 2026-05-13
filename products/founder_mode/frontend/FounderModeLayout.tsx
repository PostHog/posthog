import { useActions, useValues } from 'kea'

import { cn, InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea, ScrollArea } from '@posthog/quill'

import { SceneExport } from 'scenes/sceneTypes'

import { Step1 } from './components/Step1'
import { Step2 } from './components/Step2'
import { Step3 } from './components/Step3'
import { Step4 } from './components/Step4'
import { founderLogic } from './scenes/founderLogic'

const STEPS = [
    { key: 'ideation', title: 'Ideation' },
    { key: 'validation', title: 'Validation' },
    { key: 'gtm', title: 'Go-to-market' },
    { key: 'launch', title: 'Launch' },
]

export function FounderModeLayout(): JSX.Element {
    const { step } = useValues(founderLogic)
    const { setStep } = useActions(founderLogic)
    const activeStep = step < 1 ? 1 : step > STEPS.length ? STEPS.length : step
    const activeIndex = activeStep - 1

    return (
        <main
            className="fixed inset-0 top-[54px] flex bg-fill-highlight-100 p-4 overflow-hidden"
            style={{
                backgroundColor: '#fff',
                backgroundSize: '13px 13px',
                backgroundImage: 'radial-gradient(1px, var(--color-gray-400), var(--color-gray-50))',
            }}
        >
            <aside className="shadow w-80 shrink-0 border rounded-sm border-border bg-surface-primary overflow-hidden flex flex-col min-h-0">
                <header className="shrink-0 px-3 py-2 border-b border-border">
                    <div className="flex items-center gap-2">
                        <span className="inline-flex items-center justify-center w-4 h-4 rounded-full border border-text-primary bg-text-primary text-bg-primary text-[10px] leading-none shrink-0">
                            {activeStep}
                        </span>
                        <span className="text-xs font-semibold text-text-primary truncate">
                            {STEPS[activeIndex].title}
                        </span>
                        <span className="ml-auto text-[10px] text-text-secondary">
                            {activeStep}/{STEPS.length}
                        </span>
                    </div>
                    <ol className="mt-1 ml-6 flex flex-wrap gap-x-2 gap-y-0.5">
                        {STEPS.map((s, index) => {
                            const isCompleted = index < activeIndex
                            const isCurrent = index === activeIndex
                            return (
                                <li key={s.key}>
                                    <button
                                        type="button"
                                        onClick={() => setStep(index + 1)}
                                        className={cn(
                                            'text-[11px] cursor-pointer hover:opacity-80 transition-opacity',
                                            isCurrent && 'font-medium text-text-primary',
                                            isCompleted && 'text-text-secondary line-through',
                                            !isCurrent && !isCompleted && 'text-text-secondary'
                                        )}
                                    >
                                        {s.title}
                                    </button>
                                </li>
                            )
                        })}
                    </ol>
                </header>
                <ScrollArea className="flex-1 min-h-0" viewportClassName="px-3 py-3">
                    <ChatThread />
                </ScrollArea>
                <footer className="shrink-0 border-t border-border p-2">
                    <InputGroup>
                        <InputGroupTextarea placeholder="Write a comment..." />
                        <InputGroupAddon align="block-end">
                            <InputGroupButton variant="primary" size="sm" className="ml-auto">
                                Post
                            </InputGroupButton>
                        </InputGroupAddon>
                    </InputGroup>
                </footer>
            </aside>
            <section
                id="steps-wrapper"
                className="flex-1 flex items-start justify-center px-12 py-10 min-h-0 overflow-y-auto"
            >
                {activeStep === 1 && <Step1 />}
                {activeStep === 2 && <Step2 />}
                {activeStep === 3 && <Step3 />}
                {activeStep === 4 && <Step4 />}
            </section>
        </main>
    )
}

interface ChatMessage {
    author: 'user' | 'agent'
    text: string
}

const DUMMY_MESSAGES: ChatMessage[] = [
    { author: 'agent', text: "Hey! What's the problem you're trying to solve?" },
    { author: 'user', text: 'Founders waste hours digging through analytics dashboards.' },
    { author: 'agent', text: 'Got it. Who feels that pain the most — solo founders, small teams?' },
    { author: 'user', text: "Solo founders and tiny teams who don't have a data person." },
    { author: 'agent', text: 'Nice. Want to sketch the smallest possible version we could ship?' },
    { author: 'user', text: 'Yeah — basically a chat that answers product questions from PostHog data.' },
    { author: 'agent', text: 'Perfect starting point. Let me write up the scope cuts.' },
]

function ChatThread(): JSX.Element {
    return (
        <div className="space-y-3">
            {DUMMY_MESSAGES.map((msg, idx) => (
                <div key={idx} className={cn('flex', msg.author === 'user' ? 'justify-end' : 'justify-start')}>
                    <div
                        className={cn(
                            'max-w-[80%] rounded-md px-3 py-2 text-xs leading-snug',
                            msg.author === 'user'
                                ? 'bg-text-primary text-bg-primary'
                                : 'bg-fill-highlight-100 text-text-primary'
                        )}
                    >
                        {msg.text}
                    </div>
                </div>
            ))}
        </div>
    )
}

export const scene: SceneExport = {
    component: FounderModeLayout,
    logic: founderLogic,
}
