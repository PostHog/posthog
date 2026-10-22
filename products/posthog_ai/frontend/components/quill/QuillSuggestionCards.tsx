import type { QuillStarterPrompt } from './quillStarterPrompts'

export interface QuillSuggestionCardsProps {
    prompts: readonly QuillStarterPrompt[]
    onSelect: (prompt: QuillStarterPrompt) => void
}

export function QuillSuggestionCards({ prompts, onSelect }: QuillSuggestionCardsProps): JSX.Element {
    return (
        <div data-quill className="@container/suggestions flex w-full flex-col gap-2">
            <span className="px-2.5 text-xs font-medium text-muted-foreground">Suggestions</span>
            <div className="grid grid-cols-1 gap-2 @md/suggestions:grid-cols-2">
                {prompts.map((prompt) => (
                    <button
                        key={prompt.label}
                        type="button"
                        onClick={() => onSelect(prompt)}
                        className="flex w-full cursor-pointer items-start gap-2.5 rounded-xl border border-border bg-card px-2.5 py-2 text-left shadow-sm transition-colors hover:bg-fill-hover"
                        data-attr="task-composer-starter-prompt"
                    >
                        <span
                            className={`flex size-6 shrink-0 items-center justify-center rounded-md text-sm ${prompt.tone}`}
                        >
                            {prompt.icon}
                        </span>
                        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                            <span className="truncate text-xs font-medium text-card-foreground">{prompt.label}</span>
                            <span className="line-clamp-1 text-xs text-muted-foreground">{prompt.description}</span>
                        </span>
                    </button>
                ))}
            </div>
        </div>
    )
}
