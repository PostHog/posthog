import { IconInfo } from '@posthog/icons'
import { Field, FieldTitle, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { QuillSurfaceContext } from 'lib/components/QuillSurface/quillSurfaceContext'

import type { EditorFilterItemsProps } from './EditorFilterItems'

export function QuillEditorFilterItems({ editorFilters, insightProps }: EditorFilterItemsProps): JSX.Element {
    return (
        <QuillSurfaceContext.Provider value>
            {editorFilters.map(({ label: Label, tooltip, showOptional, key, component: Component }) => {
                if (Component && Component.name === 'component') {
                    throw new Error(
                        `Component for filter ${key} is an anonymous function, which is not a valid React component! Use a named function instead.`
                    )
                }
                const label = typeof Label === 'function' ? <Label insightProps={insightProps} /> : Label
                return (
                    <Field key={key} className="min-w-0 gap-1.5">
                        {(label || tooltip) && (
                            <FieldTitle className="flex items-center gap-1">
                                {label}
                                {showOptional && <span className="font-normal text-muted-foreground">(optional)</span>}
                                {tooltip && (
                                    <Tooltip>
                                        <TooltipTrigger
                                            render={<span className="inline-flex text-muted-foreground" />}
                                            aria-label="More info"
                                        >
                                            <IconInfo className="size-4" />
                                        </TooltipTrigger>
                                        <TooltipContent>{tooltip}</TooltipContent>
                                    </Tooltip>
                                )}
                            </FieldTitle>
                        )}
                        {Component ? (
                            // The fields are still LemonUI, which reads colour variables that quill redefines.
                            <div data-not-quill className="min-w-0">
                                <Component insightProps={insightProps} />
                            </div>
                        ) : null}
                    </Field>
                )
            })}
        </QuillSurfaceContext.Provider>
    )
}
