import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Spinner } from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'

import { InitialPermissionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import type { ApprovalCardOption } from '../policy/permissionUtils'
import type { PermissionMode } from '../utils/composerModes'
import { ComposerModePicker } from './composer/ComposerModePicker'

const MODE_IDS: string[] = Object.values(InitialPermissionModeEnumApi)

export function isPermissionModeOptionId(optionId: string): optionId is PermissionMode {
    return MODE_IDS.includes(optionId)
}

// The mode last used to approve a plan, remembered across runs — `/code`'s `lastPlanApprovalMode` setting.
const LAST_APPROVAL_MODE_KEY = 'posthog-ai.lastPlanApprovalMode'

function readLastApprovalMode(): string | null {
    try {
        return window.localStorage.getItem(LAST_APPROVAL_MODE_KEY)
    } catch {
        return null
    }
}

function writeLastApprovalMode(mode: string): void {
    try {
        window.localStorage.setItem(LAST_APPROVAL_MODE_KEY, mode)
    } catch {
        // Storage unavailable (private mode / quota) — the pre-selection just won't persist.
    }
}

const MAX_FEEDBACK_HEIGHT = 200

function autosize(el: HTMLTextAreaElement): void {
    el.style.height = 'auto'
    const next = Math.min(el.scrollHeight, MAX_FEEDBACK_HEIGHT)
    el.style.height = `${next}px`
    // Only enable scrolling when content actually exceeds the cap — "auto" surfaces a track on macOS
    // when "Always show scrollbars" is set.
    el.style.overflowY = el.scrollHeight > MAX_FEEDBACK_HEIGHT ? 'auto' : 'hidden'
}

interface InlineEditableTextProps {
    value: string
    placeholder: string
    active: boolean
    disabled?: boolean
    onChange: (value: string) => void
    onNavigateUp: () => void
    onNavigateDown: () => void
    onEscape: () => void
    onSubmit: () => void
}

/** Port of `/code`'s `InlineEditableText` — the borderless autosizing textarea that IS the reject row. */
function InlineEditableText({
    value,
    placeholder,
    active,
    disabled,
    onChange,
    onNavigateUp,
    onNavigateDown,
    onEscape,
    onSubmit,
}: InlineEditableTextProps): JSX.Element {
    const textareaRef = useRef<HTMLTextAreaElement>(null)

    useEffect(() => {
        const el = textareaRef.current
        if (!el) {
            return
        }
        if (active) {
            el.focus()
        } else if (document.activeElement === el) {
            // Leaving the row must also drop focus, or the still-focused textarea would keep
            // swallowing the selector's global keyboard shortcuts.
            el.blur()
        }
    }, [active])

    // Track parent-driven value changes (e.g. clearing after submit) through the rendered DOM.
    useEffect(() => {
        const el = textareaRef.current
        if (el) {
            autosize(el)
        }
    }, [value])

    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
            if (e.key === 'Escape') {
                e.preventDefault()
                onEscape()
            } else if (e.key === 'ArrowUp') {
                const el = e.currentTarget
                if (el.selectionStart === 0 && el.selectionEnd === 0) {
                    e.preventDefault()
                    onNavigateUp()
                }
            } else if (e.key === 'ArrowDown') {
                const el = e.currentTarget
                if (el.selectionStart === el.value.length && el.selectionEnd === el.value.length) {
                    e.preventDefault()
                    onNavigateDown()
                }
            } else if (e.key === 'Tab') {
                e.preventDefault()
                onNavigateDown()
            } else if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                onSubmit()
            }
        },
        [onNavigateUp, onNavigateDown, onEscape, onSubmit]
    )

    return (
        <textarea
            ref={textareaRef}
            value={value}
            placeholder={placeholder}
            disabled={disabled}
            onChange={(e) => {
                onChange(e.target.value)
                autosize(e.target)
            }}
            onKeyDown={handleKeyDown}
            onClick={(e) => e.stopPropagation()}
            rows={1}
            className="block w-full cursor-text resize-none overflow-y-hidden break-words border-0 bg-transparent p-0 font-medium text-[13px] leading-4 outline-none placeholder:text-muted focus:outline-none"
            style={{
                userSelect: active ? 'auto' : 'none',
                pointerEvents: active ? 'auto' : 'none',
            }}
        />
    )
}

export interface PlanApprovalSelectorProps {
    /** The wire's approve options, unfiltered and in wire order — their optionIds are the permission modes. */
    approveOptions: ApprovalCardOption[]
    /** The wire's reject option (reject-with-feedback), driving the inline feedback row. */
    rejectOption?: ApprovalCardOption
    /** True while the permission response POST is in flight — blocks approve/reject re-submission. */
    responding: boolean
    onApprove: (optionId: string) => void
    onReject: (optionId: string, feedback: string) => void
    /** Esc — cancels the permission and interrupts the turn, like `/code`'s `cancelPermissionAndPrompt`. */
    onCancel: () => void
}

/**
 * Plan-approval selector — a port of `/code`'s `PlanApprovalSelector`: an "Approve and proceed" line
 * with the per-mode "Yes, and…" wire options collapsed into the shared mode dropdown beside it, and
 * the inline reject-with-feedback line below. Window-level keyboard nav (no focus required — works
 * while focus rests on the page body or inside the card, without hijacking keys from elements
 * elsewhere on the page): ↑↓ move between the two rows, Enter approves, Tab/Shift+Tab cycles the
 * permission mode, digits act on rows, Esc cancels. Approve
 * → `onApprove(<modeOptionId>)`; reject requires
 * feedback text → `onReject(<rejectOptionId>, feedback)` (empty Enter is a no-op). The approved mode
 * is remembered and pre-selected on the next plan.
 */
export function PlanApprovalSelector({
    approveOptions,
    rejectOption,
    responding,
    onApprove,
    onReject,
    onCancel,
}: PlanApprovalSelectorProps): JSX.Element {
    const modes = useMemo(
        () => approveOptions.map((option) => option.optionId).filter(isPermissionModeOptionId),
        [approveOptions]
    )

    // Resolution order mirrors `/code`: the remembered last-approved mode, then "auto", then manual
    // approval, then any single-use (`allow_once` → primary) option, then the first offered.
    const initialMode = useMemo(() => {
        const has = (id: string): boolean => modes.includes(id as PermissionMode)
        const remembered = readLastApprovalMode()
        return (
            (remembered && has(remembered) ? (remembered as PermissionMode) : undefined) ??
            (has(InitialPermissionModeEnumApi.Auto) ? InitialPermissionModeEnumApi.Auto : undefined) ??
            (has(InitialPermissionModeEnumApi.Default) ? InitialPermissionModeEnumApi.Default : undefined) ??
            modes.find((mode) => approveOptions.find((o) => o.optionId === mode)?.primary) ??
            modes[0]
        )
    }, [modes, approveOptions])

    const [selectedMode, setSelectedMode] = useState<PermissionMode | undefined>(initialMode)
    const [selectedIndex, setSelectedIndex] = useState(0)
    const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
    const [feedback, setFeedback] = useState('')
    const containerRef = useRef<HTMLDivElement>(null)

    const rejectIndex = rejectOption ? 1 : -1
    const rowCount = rejectOption ? 2 : 1
    // The reject row is the inline feedback textarea, so "on the reject row" and "editing feedback"
    // are the same state — derive it, don't duplicate it.
    const rejectSelected = selectedIndex === rejectIndex

    // The approve row needs no focus management — the shortcuts are window-level; the reject row's
    // textarea focuses itself via its `active` prop.
    const selectRow = (index: number): void => {
        setHoveredIndex(null)
        setSelectedIndex(index)
    }

    const approve = (): void => {
        if (!selectedMode || responding) {
            return
        }
        // Remember this choice so the next plan approval pre-selects it.
        writeLastApprovalMode(selectedMode)
        onApprove(selectedMode)
    }

    const submitReject = (): void => {
        const text = feedback.trim()
        // Reject requires feedback text; empty Enter is a no-op (use Esc to cancel instead).
        if (!rejectOption || !text || responding) {
            return
        }
        onReject(rejectOption.optionId, text)
    }

    const moveSelection = (delta: number): void => {
        selectRow((selectedIndex + delta + rowCount) % rowCount)
    }

    // Tab cycles the permission mode in place (`/code` parity) — no focus juggling with the dropdown.
    const cycleMode = (delta: number): void => {
        if (!selectedMode || modes.length < 2) {
            return
        }
        const idx = modes.indexOf(selectedMode)
        setSelectedMode(modes[(idx + delta + modes.length) % modes.length])
    }

    // Window-level shortcuts, so keyboard nav works without the selector being focused (the CLI-like
    // default is focus parked on the page body). Everything else keeps its keys: the reject textarea
    // owns the keyboard while its row is selected, form fields are left alone, and focus resting on
    // any element outside the card keeps native Tab/Enter behavior.
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent): void => {
            if (rejectSelected || e.defaultPrevented) {
                return
            }
            const target = e.target
            if (
                target instanceof HTMLElement &&
                (target.tagName === 'INPUT' ||
                    target.tagName === 'TEXTAREA' ||
                    target.tagName === 'SELECT' ||
                    target.isContentEditable ||
                    // While the mode dropdown is open its menu owns the keyboard — Enter there picks a
                    // mode, it must not approve the plan.
                    target.closest('[role="menu"]') !== null)
            ) {
                return
            }
            // A key pressed while focus sits on some other element (a nav link, a button in another
            // panel) keeps its native behavior — Tab must keep moving focus and Enter must keep
            // activating that element. The selector owns the keyboard only while focus rests on the
            // page body (the CLI-like default) or within its own subtree.
            if (target instanceof HTMLElement && target !== document.body && !containerRef.current?.contains(target)) {
                return
            }
            switch (e.key) {
                case 'ArrowUp':
                    e.preventDefault()
                    moveSelection(-1)
                    break
                case 'ArrowDown':
                    e.preventDefault()
                    moveSelection(1)
                    break
                case 'Tab':
                    e.preventDefault()
                    cycleMode(e.shiftKey ? -1 : 1)
                    break
                case 'Enter':
                    e.preventDefault()
                    approve()
                    break
                case 'Escape':
                    e.preventDefault()
                    e.stopPropagation()
                    onCancel()
                    break
                default:
                    if (/^[1-9]$/.test(e.key) && !e.metaKey && !e.ctrlKey) {
                        const idx = Number.parseInt(e.key, 10) - 1
                        if (idx < rowCount) {
                            e.preventDefault()
                            if (idx === 0) {
                                approve()
                            } else {
                                selectRow(idx)
                            }
                        }
                    }
            }
        }

        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    })

    const rowClass = (index: number): string =>
        cn(
            '-mx-3 cursor-pointer select-none rounded px-3 py-1',
            selectedIndex === index
                ? 'bg-accent-highlight-secondary'
                : hoveredIndex === index
                  ? 'bg-fill-button-tertiary-hover'
                  : 'bg-transparent'
        )

    const caret = (index: number): JSX.Element => (
        <span
            className={cn(
                'w-[1ch] shrink-0 text-[13px] leading-4',
                selectedIndex === index ? 'text-accent' : 'text-muted'
            )}
        >
            {selectedIndex === index ? '›' : ''}
        </span>
    )

    const number = (index: number): JSX.Element => (
        <span
            className={cn(
                'min-w-4 shrink-0 whitespace-nowrap text-right text-[13px] leading-4',
                selectedIndex === index || hoveredIndex === index ? 'text-accent' : 'text-muted'
            )}
        >
            {index + 1}.
        </span>
    )

    const approveActive = selectedIndex === 0 || hoveredIndex === 0

    return (
        <div ref={containerRef} className="rounded border bg-surface-primary p-3">
            <div className="flex flex-col gap-2">
                <span className="font-medium text-[13px] text-accent">Implementation Plan</span>

                <div>
                    <p className="mb-2 text-[13px]">Approve this plan to proceed?</p>

                    <div className="flex flex-col gap-1 px-2">
                        {/* Approve line — mode dropdown (shared ComposerModePicker) beside it. */}
                        <div
                            onClick={approve}
                            onMouseEnter={() => setHoveredIndex(0)}
                            onMouseLeave={() => setHoveredIndex(null)}
                            className={rowClass(0)}
                        >
                            <div className="flex items-center gap-2 leading-4">
                                {caret(0)}
                                {number(0)}
                                <div className="flex min-w-0 flex-1 items-center justify-between gap-2 leading-4">
                                    <span
                                        className={cn(
                                            'whitespace-pre-wrap font-medium text-[13px] leading-4',
                                            approveActive ? 'text-accent' : 'text-primary'
                                        )}
                                    >
                                        Approve and proceed
                                    </span>
                                    {responding ? (
                                        <Spinner className="size-4" />
                                    ) : (
                                        selectedMode && (
                                            <div onClick={(e) => e.stopPropagation()}>
                                                <ComposerModePicker
                                                    selectedMode={selectedMode}
                                                    onModeChange={setSelectedMode}
                                                    modes={modes}
                                                />
                                            </div>
                                        )
                                    )}
                                </div>
                            </div>
                        </div>

                        {/* Reject line — the inline feedback textarea. */}
                        {rejectOption && (
                            <div
                                onClick={() => selectRow(1)}
                                onMouseEnter={() => setHoveredIndex(1)}
                                onMouseLeave={() => setHoveredIndex(null)}
                                className={rowClass(1)}
                            >
                                <div className="flex items-center gap-2 leading-4">
                                    {caret(1)}
                                    {number(1)}
                                    <div className="min-w-0 flex-1 leading-4">
                                        <InlineEditableText
                                            value={feedback}
                                            placeholder="Type here to tell the agent what to do differently"
                                            active={rejectSelected}
                                            disabled={responding}
                                            onChange={setFeedback}
                                            onNavigateUp={() => selectRow(0)}
                                            onNavigateDown={() => selectRow(0)}
                                            onEscape={() => {
                                                setFeedback('')
                                                selectRow(0)
                                            }}
                                            onSubmit={submitReject}
                                        />
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>

                    <p className="mt-2 mb-0 text-[13px] text-muted">
                        Enter to select · Tab to change mode · ↑↓ to navigate · Esc to cancel
                    </p>
                </div>
            </div>
        </div>
    )
}
