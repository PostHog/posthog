import type { CSSProperties } from 'react'

import { cn } from 'lib/utils/css-classes'

import { TodayObjectIcon } from '~/layout/today/TodayObjectIcon'

import type { QuillStarterPrompt } from './quillStarterPrompts'

export interface QuillSuggestionCardsProps {
    prompts: readonly QuillStarterPrompt[]
    onSelect: (prompt: QuillStarterPrompt) => void
    visible: boolean
}

const STAGGER_MS = 30

export function QuillSuggestionCards({ prompts, onSelect, visible }: QuillSuggestionCardsProps): JSX.Element {
    return (
        <div
            data-quill
            aria-hidden={!visible}
            className={cn(
                '@container/suggestions flex w-full flex-col gap-1 transition-opacity ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none',
                visible ? 'opacity-100 duration-200' : 'pointer-events-none opacity-0 duration-100'
            )}
        >
            <span className="px-3 text-xs font-medium text-muted-foreground">Suggestions</span>
            <ul className="m-0 grid list-none grid-cols-1 p-0 @md/suggestions:grid-cols-2">
                {prompts.map((prompt, index) => (
                    <li
                        key={prompt.label}
                        style={{ '--stagger': `${visible ? index * STAGGER_MS : 0}ms` } as CSSProperties}
                        className={cn(
                            'transition-[opacity,translate] delay-(--stagger) ease-[cubic-bezier(0.23,1,0.32,1)] starting:translate-y-1 starting:opacity-0 motion-reduce:transition-none',
                            visible
                                ? 'translate-y-0 opacity-100 duration-300'
                                : 'translate-y-0.5 opacity-0 duration-100'
                        )}
                    >
                        <button
                            type="button"
                            onClick={() => onSelect(prompt)}
                            tabIndex={visible ? undefined : -1}
                            className="grid w-full cursor-pointer grid-cols-[26px_minmax(0,1fr)] items-start gap-3 rounded-lg px-3 py-2 text-left transition-[background-color,scale] duration-150 ease-out hover:bg-fill-hover active:scale-[0.98] motion-reduce:transition-none"
                            data-attr="task-composer-starter-prompt"
                        >
                            <TodayObjectIcon type={prompt.iconType} className="mt-px -ml-px [--icon-stack-size:22px]" />
                            <span className="min-w-0">
                                <span className="block truncate text-sm text-foreground">{prompt.label}</span>
                                <span className="block truncate text-[13px] leading-[18px] text-muted-foreground">
                                    {prompt.description}
                                </span>
                            </span>
                        </button>
                    </li>
                ))}
            </ul>
        </div>
    )
}
