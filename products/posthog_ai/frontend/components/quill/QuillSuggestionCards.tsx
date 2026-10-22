import { type CSSProperties, useEffect, useRef, useState } from 'react'

import { cn } from 'lib/utils/css-classes'

import { TodayObjectIcon } from '~/layout/today/TodayObjectIcon'

import type { QuillStarterPrompt } from './quillStarterPrompts'

export interface QuillSuggestionCardsProps {
    prompts: readonly QuillStarterPrompt[]
    onSelect: (prompt: QuillStarterPrompt) => void
    visible: boolean
}

const ENTER_STAGGER_MS = 30
const EXIT_RIPPLE_MS = 25
const PICKED_HOLD_MS = 60
const FILL_AFTER_MS = 200

function delayFor(index: number, visible: boolean, pickedIndex: number): number {
    if (visible) {
        return index * ENTER_STAGGER_MS
    }
    if (pickedIndex === -1) {
        return 0
    }
    return index === pickedIndex ? PICKED_HOLD_MS : Math.abs(index - pickedIndex) * EXIT_RIPPLE_MS
}

export function QuillSuggestionCards({ prompts, onSelect, visible }: QuillSuggestionCardsProps): JSX.Element {
    const [pickedLabel, setPickedLabel] = useState<string | null>(null)
    const shown = visible && pickedLabel === null
    const pickedIndex = shown ? -1 : prompts.findIndex((prompt) => prompt.label === pickedLabel)
    const wasVisible = useRef(visible)
    const fillTimer = useRef<ReturnType<typeof setTimeout>>()

    useEffect(() => {
        if (visible && !wasVisible.current) {
            setPickedLabel(null)
        }
        wasVisible.current = visible
    }, [visible])

    useEffect(() => () => clearTimeout(fillTimer.current), [])

    const pick = (prompt: QuillStarterPrompt): void => {
        if (pickedLabel !== null) {
            return
        }
        setPickedLabel(prompt.label)
        const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
        fillTimer.current = setTimeout(() => onSelect(prompt), reducedMotion ? 0 : FILL_AFTER_MS)
    }

    return (
        <div data-quill aria-hidden={!shown} className="@container/suggestions flex w-full flex-col gap-1">
            <span
                className={cn(
                    'px-3 text-xs font-medium text-muted-foreground transition-opacity ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none',
                    shown ? 'opacity-100 duration-200' : 'opacity-0 duration-100'
                )}
            >
                Suggestions
            </span>
            <ul
                className={cn(
                    'm-0 grid list-none grid-cols-1 p-0 @md/suggestions:grid-cols-2',
                    !shown && 'pointer-events-none'
                )}
            >
                {prompts.map((prompt, index) => {
                    const picked = index === pickedIndex
                    return (
                        <li
                            key={prompt.label}
                            style={{ '--delay': `${delayFor(index, shown, pickedIndex)}ms` } as CSSProperties}
                            className={cn(
                                'transition-[opacity,translate,scale] delay-(--delay) ease-[cubic-bezier(0.23,1,0.32,1)] starting:translate-y-1 starting:opacity-0 motion-reduce:transition-none',
                                shown && 'translate-y-0 opacity-100 duration-300',
                                !shown && picked && '-translate-y-2 scale-[0.98] opacity-0 duration-200',
                                !shown && !picked && 'translate-y-0.5 opacity-0 duration-150'
                            )}
                        >
                            <button
                                type="button"
                                onClick={() => pick(prompt)}
                                tabIndex={shown ? undefined : -1}
                                className={cn(
                                    'grid w-full cursor-pointer grid-cols-[26px_minmax(0,1fr)] items-start gap-3 rounded-lg px-3 py-2 text-left transition-[background-color,scale] duration-150 ease-out hover:bg-fill-hover active:scale-[0.98] motion-reduce:transition-none',
                                    picked && 'bg-fill-selected'
                                )}
                                data-attr="task-composer-starter-prompt"
                            >
                                <TodayObjectIcon
                                    type={prompt.iconType}
                                    className="mt-px -ml-px [--icon-stack-size:22px]"
                                />
                                <span className="min-w-0">
                                    <span className="block truncate text-sm text-foreground">{prompt.label}</span>
                                    <span className="block truncate text-[13px] leading-[18px] text-muted-foreground">
                                        {prompt.description}
                                    </span>
                                </span>
                            </button>
                        </li>
                    )
                })}
            </ul>
        </div>
    )
}
