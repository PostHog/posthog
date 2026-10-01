import { useActions, useValues } from 'kea'
import { ChangeEvent, KeyboardEvent, useEffect, useRef } from 'react'

import { IconArrowRight } from '@posthog/icons'
import {
    Button,
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupText,
    InputGroupTextarea,
} from '@posthog/quill'

import { spaceLabel } from '~/layout/today/todaySpacesLogic'

import { spaceLoopsLogic } from './spaceLoopsLogic'

function quickStarts(spaceName: string): { label: string; prompt: string }[] {
    return [
        { label: 'Digest to feed', prompt: `On a schedule, post a short digest to ${spaceName}'s feed summarizing ` },
        { label: 'Refresh a canvas', prompt: `On a schedule, refresh a canvas in ${spaceName} with ` },
        { label: 'Watch and report', prompt: 'Watch for changes in ' },
    ]
}

/** The "describe it and an agent builds it" box under the loops, like PostHog Desktop's loop builder. */
export function SpaceLoopBuilderComposer({ id }: { id: string }): JSX.Element {
    const { builderDraft, builderFocusRequest, space } = useValues(spaceLoopsLogic({ id }))
    const { setBuilderDraft, submitBuilder, focusBuilder } = useActions(spaceLoopsLogic({ id }))
    const groupRef = useRef<HTMLDivElement>(null)
    const spaceName = space ? spaceLabel(space) : 'this space'

    useEffect(() => {
        if (!builderFocusRequest) {
            return
        }
        const textarea = groupRef.current?.querySelector('textarea')
        textarea?.focus()
        textarea?.setSelectionRange(textarea.value.length, textarea.value.length)
        groupRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }, [builderFocusRequest])

    return (
        <div className="sticky bottom-0 flex flex-col gap-2 bg-background pt-2 pb-4">
            <div className="flex flex-wrap gap-2">
                {quickStarts(spaceName).map(({ label, prompt }) => (
                    <Button
                        key={label}
                        size="sm"
                        variant="outline"
                        className="rounded-full"
                        onClick={() => {
                            setBuilderDraft(prompt)
                            focusBuilder()
                        }}
                        data-attr="today-space-loop-quick-start"
                    >
                        {label}
                    </Button>
                ))}
            </div>
            <InputGroup ref={groupRef}>
                <InputGroupTextarea
                    rows={2}
                    value={builderDraft}
                    placeholder={`What should ${spaceName} keep an eye on?`}
                    aria-label="Describe the loop"
                    onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setBuilderDraft(event.target.value)}
                    onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                        if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                            event.preventDefault()
                            submitBuilder()
                        }
                    }}
                    data-attr="today-space-loop-builder-input"
                />
                <InputGroupAddon align="block-end">
                    <InputGroupText>
                        An agent builds the loop with you, then creates it when you confirm.
                    </InputGroupText>
                    <InputGroupButton
                        size="icon-sm"
                        variant="primary"
                        className="ml-auto"
                        aria-label="Build the loop with an agent"
                        disabled={!builderDraft.trim()}
                        onClick={submitBuilder}
                        data-attr="today-space-loop-builder-submit"
                    >
                        <IconArrowRight />
                    </InputGroupButton>
                </InputGroupAddon>
            </InputGroup>
        </div>
    )
}
