import { TodayObjectIcon } from '~/layout/today/TodayObjectIcon'

import type { QuillStarterPrompt } from './quillStarterPrompts'

export interface QuillSuggestionCardsProps {
    prompts: readonly QuillStarterPrompt[]
    onSelect: (prompt: QuillStarterPrompt) => void
}

export function QuillSuggestionCards({ prompts, onSelect }: QuillSuggestionCardsProps): JSX.Element {
    return (
        <div data-quill className="@container/suggestions flex w-full flex-col gap-1">
            <span className="px-3 text-xs font-medium text-muted-foreground">Suggestions</span>
            <ul className="m-0 grid list-none grid-cols-1 p-0 @md/suggestions:grid-cols-2">
                {prompts.map((prompt) => (
                    <li key={prompt.label}>
                        <button
                            type="button"
                            onClick={() => onSelect(prompt)}
                            className="grid w-full cursor-pointer grid-cols-[26px_minmax(0,1fr)] items-start gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-fill-hover"
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
