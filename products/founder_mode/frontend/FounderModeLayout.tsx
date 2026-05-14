import { useActions, useValues } from 'kea'
import * as React from 'react'

import { IconCheck } from '@posthog/icons'
import { Button, cn, InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from '@posthog/quill'

import { SceneExport } from 'scenes/sceneTypes'

import { CanvasNote, CanvasSlot, FOUNDER_CHAT_SCRIPT, founderChatLogic } from './founderChatLogic'
import { founderLogic } from './scenes/founderLogic'

const CARD_WIDTH = 480
const STACK_TOP = 60 // px from container top — pile centered horizontally, above the active card
const STACK_STEP = 4 // each new pile card sits this many px lower
const X_JITTER = 2 // small horizontal jitter so the pile looks hand-placed
const ACTIVE_TOP = 280 // px from container top — current active card position
const UPCOMING_STEP = 4 // each upcoming card peeks this many px below the active card
const REVIEW_STACK_HEIGHT = 220 // approximate height of the visible review-mode stack
const QUESTION_BOTTOM = 170 // px from container bottom — question lives just above input
const COMPOSER_BOTTOM = 24 // px from container bottom — floating input

const QUESTION_FADE_MS = 500
const CARD_FLY_MS = 900

const Z_PILE_BASE = 1
const Z_UPCOMING_BASE = 50
const Z_QUESTION = 200
const Z_ACTIVE = 300

const FOUNDER_KEYFRAMES = `
@keyframes founder-check-pop {
    0% { opacity: 0; transform: scale(0.4) rotate(-15deg); }
    60% { opacity: 1; transform: scale(1.15) rotate(5deg); }
    100% { opacity: 1; transform: scale(1) rotate(0deg); }
}
@keyframes founder-fade-opacity {
    from { opacity: 0; }
    to { opacity: 1; }
}
@keyframes founder-caret {
    0%, 50% { opacity: 1; }
    50.01%, 100% { opacity: 0; }
}
`

const QUESTION_STREAM_MS_PER_CHAR = 18

function StreamingQuestion({ message, fading }: { message: string; fading: boolean }): JSX.Element {
    const [shown, setShown] = React.useState('')
    const doneRef = React.useRef(false)

    React.useEffect(() => {
        setShown('')
        doneRef.current = false
        let i = 0
        const id = window.setInterval(() => {
            i++
            setShown(message.slice(0, i))
            if (i >= message.length) {
                window.clearInterval(id)
                doneRef.current = true
            }
        }, QUESTION_STREAM_MS_PER_CHAR)
        return () => window.clearInterval(id)
    }, [message])

    const isStreaming = shown.length < message.length
    return (
        <div
            className={cn(
                'px-4 py-2 rounded-md border border-border-bold/40 bg-white text-sm text-text-primary shadow-sm transition-opacity ease-out text-left',
                fading ? 'opacity-0' : 'opacity-100'
            )}
            style={{ transitionDuration: `${QUESTION_FADE_MS}ms` }}
        >
            {shown}
            {isStreaming && (
                <span
                    className="inline-block w-[1px] h-[1em] align-text-bottom bg-text-primary ml-[2px]"
                    style={{ animation: 'founder-caret 900ms steps(2, end) infinite' }}
                />
            )}
        </div>
    )
}

function rotationFor(idx: number): number {
    return idx % 2 === 0 ? -0.5 : 0.4
}

function xOffsetFor(idx: number): number {
    return ((idx % 3) - 1) * X_JITTER
}

function stackTopFor(idx: number): number {
    return STACK_TOP + idx * STACK_STEP
}

// Every script beat that has a canvas slot — the full set of cards we'll fill in.
const ALL_SLOTS: CanvasSlot[] = FOUNDER_CHAT_SCRIPT.map((b) => b.canvasSlot).filter((s): s is CanvasSlot => !!s)

export function FounderModeLayout(): JSX.Element {
    const { phase, currentAgentMessage, draft, activeSlot, canvasNotes } = useValues(founderChatLogic)
    const { sendUserMessage } = useActions(founderChatLogic)

    const [questionFading, setQuestionFading] = React.useState(false)
    const [cardFlying, setCardFlying] = React.useState(false)
    const submitting = React.useRef(false)
    const lastQuestionRef = React.useRef(currentAgentMessage)

    React.useEffect(() => {
        if (lastQuestionRef.current !== currentAgentMessage) {
            lastQuestionRef.current = currentAgentMessage
            setQuestionFading(false)
            setCardFlying(false)
            submitting.current = false
        }
    }, [currentAgentMessage])

    const canSubmit = !!draft.trim() && !submitting.current && !!activeSlot && phase === 'chat'
    const targetPileIdx = canvasNotes.length

    const submit = (): void => {
        if (!canSubmit) {
            return
        }
        submitting.current = true
        setQuestionFading(true)
        window.setTimeout(() => {
            setCardFlying(true)
            window.setTimeout(() => {
                sendUserMessage(draft)
            }, CARD_FLY_MS)
        }, QUESTION_FADE_MS)
    }

    return (
        <main
            className="fixed inset-0 top-[54px] flex flex-col bg-fill-highlight-100 overflow-hidden"
            style={{
                backgroundColor: '#fff',
                backgroundSize: '13px 13px',
                backgroundImage: 'radial-gradient(1px, var(--color-gray-400), var(--color-gray-50))',
            }}
        >
            <style>{FOUNDER_KEYFRAMES}</style>
            <DebugMenu />
            <section className="flex-1 relative overflow-hidden">
                {(phase === 'chat' || phase === 'review' || phase === 'summarizing') && (
                    <Stage questionFading={questionFading} cardFlying={cardFlying} targetPileIdx={targetPileIdx} />
                )}
                {phase === 'validation' && <ValidationSession />}
            </section>
            {phase === 'chat' && <FloatingComposer onSubmit={submit} canSubmit={canSubmit} />}
        </main>
    )
}

function DebugMenu(): JSX.Element {
    const { phase } = useValues(founderChatLogic)
    const { debugFillAndJumpToReview } = useActions(founderChatLogic)
    return (
        <div className="absolute top-2 right-3 z-[400] flex gap-2 text-[10px] uppercase tracking-wide text-text-secondary">
            <span className="px-1.5 py-0.5 rounded bg-fill-highlight-100 border border-border">debug</span>
            <button
                type="button"
                onClick={debugFillAndJumpToReview}
                disabled={phase !== 'chat'}
                className="px-2 py-0.5 rounded border border-border bg-white hover:bg-fill-highlight-100 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
                Skip to review
            </button>
        </div>
    )
}

function Stage({
    questionFading,
    cardFlying,
    targetPileIdx,
}: {
    questionFading: boolean
    cardFlying: boolean
    targetPileIdx: number
}): JSX.Element {
    const {
        phase,
        canvasNotes,
        currentAgentMessage,
        activeSlot,
        draft,
        reviewIndex,
        editingKey,
        summaryText,
        reviewProgress,
    } = useValues(founderChatLogic)
    const { acceptCard, denyCard, editCard, saveEdit, cancelEdit, startValidation } = useActions(founderChatLogic)

    const inChat = phase === 'chat'
    const inReview = phase === 'review'
    const inSummarizing = phase === 'summarizing'

    const activeSlotIdx = activeSlot ? ALL_SLOTS.findIndex((s) => s.key === activeSlot.key) : -1
    const flyTargetTop = stackTopFor(targetPileIdx)
    const flyTargetXOffset = xOffsetFor(targetPileIdx)
    const flyDistanceY = flyTargetTop - ACTIVE_TOP
    const flyRotation = rotationFor(targetPileIdx)

    return (
        <div className="absolute inset-0">
            {/* Cards (in chat phase: pile + active + upcoming stack) */}
            {inChat &&
                ALL_SLOTS.map((slot, slotIdx) => {
                    const placedIdx = canvasNotes.findIndex((n) => n.key === slot.key)
                    const isPlaced = placedIdx >= 0
                    const isActive = !isPlaced && activeSlot?.key === slot.key
                    const isUpcoming = !isPlaced && !isActive && activeSlotIdx >= 0 && slotIdx > activeSlotIdx

                    if (!isPlaced && !isActive && !isUpcoming) {
                        return null
                    }

                    const note = isPlaced ? canvasNotes[placedIdx] : null
                    const value = isPlaced ? (note?.value ?? '') : isActive ? draft : ''
                    const label = slot.label

                    let style: React.CSSProperties = {
                        position: 'absolute',
                        width: CARD_WIDTH,
                        transition: `top ${CARD_FLY_MS}ms cubic-bezier(0.4, 0, 0.2, 1), left ${CARD_FLY_MS}ms cubic-bezier(0.4, 0, 0.2, 1), transform ${CARD_FLY_MS}ms cubic-bezier(0.4, 0, 0.2, 1), opacity 400ms ease-out`,
                    }

                    if (isPlaced) {
                        // Same horizontal anchor as the active card so flight is purely
                        // vertical — no diagonal, no post-commit wiggle.
                        style = {
                            ...style,
                            top: stackTopFor(placedIdx),
                            left: '50%',
                            transform: `translate(${-CARD_WIDTH / 2 + xOffsetFor(placedIdx)}px, 0px) rotate(${rotationFor(placedIdx)}deg)`,
                            zIndex: Z_PILE_BASE + placedIdx,
                        }
                    } else if (isActive) {
                        if (cardFlying) {
                            style = {
                                ...style,
                                top: ACTIVE_TOP,
                                left: '50%',
                                transform: `translate(${-CARD_WIDTH / 2 + flyTargetXOffset}px, ${flyDistanceY}px) rotate(${flyRotation}deg)`,
                                zIndex: Z_ACTIVE,
                            }
                        } else {
                            style = {
                                ...style,
                                top: ACTIVE_TOP,
                                left: '50%',
                                transform: `translate(${-CARD_WIDTH / 2}px, 0px) rotate(0deg)`,
                                zIndex: Z_ACTIVE,
                            }
                        }
                    } else if (isUpcoming) {
                        const offset = slotIdx - activeSlotIdx // 1, 2, 3 ...
                        style = {
                            ...style,
                            top: ACTIVE_TOP + offset * UPCOMING_STEP,
                            left: '50%',
                            transform: `translate(${-CARD_WIDTH / 2}px, 0px) rotate(${offset % 2 === 0 ? 0.4 : -0.4}deg)`,
                            zIndex: Z_UPCOMING_BASE - offset,
                            opacity: offset > 3 ? 0 : 1 - offset * 0.15,
                        }
                    }

                    return (
                        <div
                            key={slot.key}
                            className="px-5 py-4 border border-border-bold/40 rounded bg-white shadow-md"
                            style={style}
                        >
                            {isPlaced && (
                                <div
                                    className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-success text-white flex items-center justify-center shadow"
                                    style={{
                                        opacity: 0,
                                        transform: 'scale(0.5)',
                                        animation: 'founder-check-pop 300ms ease-out 200ms forwards',
                                    }}
                                >
                                    <IconCheck className="w-4 h-4" />
                                </div>
                            )}
                            <div className="text-[10px] uppercase tracking-wide text-text-secondary mb-1">{label}</div>
                            <div className="text-sm whitespace-pre-wrap min-h-[1.25rem] text-text-primary">
                                {value || (
                                    <span className="text-text-secondary/60">{isActive ? 'Start typing…' : ' '}</span>
                                )}
                            </div>
                        </div>
                    )
                })}

            {/* Review-phase cards (existing layout) */}
            {(inReview || inSummarizing) &&
                canvasNotes.map((note, idx) => {
                    let style: React.CSSProperties = {
                        position: 'absolute',
                        width: CARD_WIDTH,
                        transition: 'all 500ms ease-out',
                    }
                    if (inReview) {
                        const stackOffset = idx - reviewIndex
                        style = {
                            ...style,
                            top: STACK_TOP,
                            left: '50%',
                            transform:
                                stackOffset < 0
                                    ? `translate(${-CARD_WIDTH / 2}px, -240px) rotate(-${Math.abs(stackOffset) * 4}deg)`
                                    : `translate(${-CARD_WIDTH / 2}px, ${stackOffset * 6}px) rotate(${stackOffset * 0.6 - 0.5}deg) scale(${1 - stackOffset * 0.02})`,
                            zIndex: canvasNotes.length - Math.max(stackOffset, 0),
                            opacity: stackOffset < 0 ? 0 : stackOffset > 3 ? 0 : 1 - stackOffset * 0.15,
                        }
                    } else {
                        // summarizing
                        style = {
                            ...style,
                            top: STACK_TOP,
                            left: '50%',
                            transform: `translate(${-CARD_WIDTH / 2}px, ${idx * 2}px) rotate(${idx * 0.4 - 0.8}deg) scale(${1 - idx * 0.01})`,
                            zIndex: canvasNotes.length - idx,
                        }
                    }
                    const isTopReview = inReview && idx === reviewIndex
                    const isEditing = editingKey === note.key && isTopReview
                    return (
                        <div
                            key={note.key}
                            className="px-5 py-4 border border-border-bold/40 rounded bg-white shadow-md"
                            style={style}
                        >
                            <div className="text-[10px] uppercase tracking-wide text-text-secondary mb-1">
                                {note.label}
                            </div>
                            {isEditing ? (
                                <ReviewEditor note={note} onSave={(v) => saveEdit(note.key, v)} onCancel={cancelEdit} />
                            ) : (
                                <div className="text-sm whitespace-pre-wrap">{note.value}</div>
                            )}
                        </div>
                    )
                })}

            {/* Question — left-aligned with the textarea below, streams in char by char */}
            {inChat && currentAgentMessage && (
                <div
                    className="absolute left-0 right-0 flex justify-center pointer-events-none"
                    style={{ bottom: QUESTION_BOTTOM, zIndex: Z_QUESTION }}
                >
                    <div className="w-full max-w-xl px-4">
                        <StreamingQuestion message={currentAgentMessage} fading={questionFading} />
                    </div>
                </div>
            )}

            {inSummarizing && (
                <div
                    className="absolute left-1/2 -translate-x-1/2 pointer-events-none"
                    style={{ top: STACK_TOP + canvasNotes.length * 4 + 40 }}
                >
                    <Spinner />
                </div>
            )}

            {/* Review controls — hug the bottom of the stack */}
            {inReview && (
                <div
                    className="absolute left-1/2 -translate-x-1/2 flex items-center justify-center gap-2"
                    style={{ top: STACK_TOP + REVIEW_STACK_HEIGHT + 24 }}
                >
                    <div className="text-xs text-text-secondary mr-2">
                        Reviewing {reviewProgress.current} / {reviewProgress.total}
                    </div>
                    <Button variant="destructive" size="sm" onClick={denyCard}>
                        ✗ Deny
                    </Button>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => canvasNotes[reviewIndex] && editCard(canvasNotes[reviewIndex].key)}
                        disabled={!!editingKey}
                    >
                        ✎ Edit
                    </Button>
                    <Button variant="primary" size="sm" onClick={acceptCard}>
                        ✓ Accept
                    </Button>
                </div>
            )}

            {/* Summary stream + CTA — stacked together below the pile */}
            {inSummarizing && summaryText && (
                <div
                    className="absolute left-1/2 -translate-x-1/2 max-w-2xl text-center flex flex-col items-center gap-6"
                    style={{ top: STACK_TOP + REVIEW_STACK_HEIGHT + 24 }}
                >
                    <div className="text-lg leading-relaxed whitespace-pre-wrap">{summaryText}</div>
                    {summaryText.endsWith('jump into validation.') && (
                        <Button variant="primary" size="sm" onClick={startValidation}>
                            Jump into validation →
                        </Button>
                    )}
                </div>
            )}
        </div>
    )
}

function FloatingComposer({ onSubmit, canSubmit }: { onSubmit: () => void; canSubmit: boolean }): JSX.Element {
    const { draft, activeSlot } = useValues(founderChatLogic)
    const { setDraft } = useActions(founderChatLogic)

    return (
        <div
            className="absolute left-0 right-0 flex justify-center pointer-events-none"
            style={{ bottom: COMPOSER_BOTTOM }}
        >
            <div className="pointer-events-auto w-full max-w-xl px-4">
                <InputGroup className="shadow-lg bg-white border border-border-bold/40 rounded">
                    <InputGroupTextarea
                        placeholder={activeSlot ? 'Type your answer…' : 'Reply…'}
                        value={draft}
                        onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setDraft(e.target.value)}
                        onKeyDown={(e: React.KeyboardEvent<HTMLTextAreaElement>) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault()
                                onSubmit()
                            }
                        }}
                        className="bg-white"
                        autoFocus
                    />
                    <InputGroupAddon align="block-end" className="bg-white">
                        <InputGroupButton
                            variant="primary"
                            size="sm"
                            className="ml-auto"
                            disabled={!canSubmit}
                            onClick={onSubmit}
                        >
                            Send
                        </InputGroupButton>
                    </InputGroupAddon>
                </InputGroup>
            </div>
        </div>
    )
}

function ReviewEditor({
    note,
    onSave,
    onCancel,
}: {
    note: CanvasNote
    onSave: (value: string) => void
    onCancel: () => void
}): JSX.Element {
    const [value, setValue] = React.useState(note.value)
    return (
        <div className="flex flex-col gap-2">
            <textarea
                className="w-full text-sm border border-border rounded px-2 py-1 min-h-[80px] resize-none bg-bg-primary"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                autoFocus
            />
            <div className="flex justify-end gap-2">
                <button
                    type="button"
                    onClick={onCancel}
                    className="px-2 py-1 text-xs rounded border border-border cursor-pointer hover:bg-fill-highlight-100"
                >
                    Cancel
                </button>
                <button
                    type="button"
                    onClick={() => onSave(value)}
                    className="px-2 py-1 text-xs rounded bg-text-primary text-bg-primary cursor-pointer"
                >
                    Save
                </button>
            </div>
        </div>
    )
}

function Spinner(): JSX.Element {
    return (
        <div
            className="w-8 h-8 border-2 border-text-secondary/30 border-t-text-primary rounded-full animate-spin"
            aria-label="Loading"
        />
    )
}

function ValidationSession(): JSX.Element {
    return (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-6">
            <h2 className="text-2xl font-semibold mb-3">Validation</h2>
            <p className="text-text-secondary max-w-md">
                Time to pressure-test the idea. (This is where we'll plug in the validation flow next.)
            </p>
        </div>
    )
}

export const scene: SceneExport = {
    component: FounderModeLayout,
    logic: founderLogic,
}
