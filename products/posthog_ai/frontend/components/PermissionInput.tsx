import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import type { ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { Button } from '@posthog/quill-primitives'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { cn } from 'lib/utils/css-classes'

import { runStreamLogic } from '../logics/runStreamLogic'
import { MarkdownMessage } from '../messages/MarkdownMessage'
import { getPermissionDisplay } from '../policy/permissionDisplayUtils'
import { isPlanPermissionRequest, mapPermissionOptions, type ApprovalCardOption } from '../policy/permissionUtils'
import type { PermissionRequestRecord } from '../types/streamTypes'
import { resolveToolCall } from '../utils/toolResolver'
import { isPlanApprovalModeOptionId, InlineEditableText, PlanApprovalSelector } from './PlanApprovalActions'
import { DiffStats } from './tool/DiffStats'
import { FilePath } from './tool/FilePath'
import { LazyDiffEditor } from './tool/LazyDiffEditor'
import { findAllDiffContent, getDiffStats, type ToolCallDiffContent } from './tool/toolDiffContent'
import { lookupToolRenderer } from './tool/toolRegistry'

interface PermissionInputProps {
    streamKey: string
    request: PermissionRequestRecord
    disabled?: boolean
}

/** Collapsed height of the payload preview, in lines — enough to scan, never enough to bury the choices. */
const PAYLOAD_COLLAPSED_LINES = 12

/**
 * Resolves the request's inner sub-tool and, if a registered entry provides a `renderPermissionPreview`,
 * returns its node (else null). Isolated + guarded so a throwing product preview can never break the
 * approval card — the card falls back to the generic evidence block.
 */
function renderRegisteredPermissionPreview(request: PermissionRequestRecord): ReactNode | null {
    try {
        const { resolvedKey, innerToolName } = resolveToolCall(request.rawToolCall)
        return lookupToolRenderer(resolvedKey, innerToolName != null).renderPermissionPreview?.(request) ?? null
    } catch (error) {
        posthog.captureException(error, { feature: 'posthog_ai_permission_preview' })
        return null
    }
}

const FEEDBACK_PLACEHOLDER = 'Tell the agent what to do differently'

interface PermissionEvidenceProps {
    request: PermissionRequestRecord
    /** Tool identity for the evidence header; omitted when the headline sentence already carries it. */
    label?: string
    payload?: string
}

interface DiffPermissionEvidenceProps {
    diffs: ToolCallDiffContent[]
    label?: string
}

function DiffPermissionEvidence({ diffs, label }: DiffPermissionEvidenceProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2 min-w-0">
            {diffs.map((diff, index) => (
                <div key={index} className="flex flex-col gap-1 min-w-0">
                    <div className="flex items-center gap-2 min-w-0 text-xs text-secondary">
                        {diff.path ? (
                            <FilePath path={diff.path} />
                        ) : (
                            label && <span className="font-medium">{label}</span>
                        )}
                        <DiffStats {...getDiffStats(diff.oldText, diff.newText)} />
                    </div>
                    <LazyDiffEditor diff={diff} path={diff.path} sideBySide />
                </div>
            ))}
        </div>
    )
}

interface PayloadPermissionEvidenceProps {
    label?: string
    payload: string
}

function PayloadPermissionEvidence({ label, payload }: PayloadPermissionEvidenceProps): JSX.Element {
    const [showAll, setShowAll] = useState(false)
    const language = payload.trim().match(/^[{[]/) ? Language.JSON : Language.Text
    const lines = payload.split('\n')
    const overflowing = lines.length > PAYLOAD_COLLAPSED_LINES
    const visible = showAll || !overflowing ? payload : lines.slice(0, PAYLOAD_COLLAPSED_LINES).join('\n')

    return (
        <div className="flex flex-col gap-1 min-w-0">
            {label && <div className="text-xs text-secondary font-medium">{label}</div>}
            <div className={cn(showAll && 'max-h-96 overflow-y-auto')}>
                <CodeSnippet language={language} className="text-xs" compact>
                    {visible}
                </CodeSnippet>
            </div>
            {overflowing && (
                <Button variant="link-muted" size="xs" className="self-start" onClick={() => setShowAll(!showAll)}>
                    {showAll ? 'Show less' : `Show all ${lines.length} lines`}
                </Button>
            )}
        </div>
    )
}

/**
 * The card's evidence block. A request whose tool call streamed `type: "diff"` content (Edit/Write, or
 * any adapter that reports a change to existing content) renders each diff with a path + stats header
 * and a side-by-side editor that collapses to unified when the container is narrow. Everything else
 * renders the payload preview capped at {@link PAYLOAD_COLLAPSED_LINES} with a "Show all" expander.
 */
function PermissionEvidence({ request, label, payload }: PermissionEvidenceProps): JSX.Element | null {
    const diffs = findAllDiffContent(request.rawToolCall.contentBlocks)

    if (diffs.length > 0) {
        return <DiffPermissionEvidence diffs={diffs} label={label} />
    }

    if (!payload) {
        return label ? <div className="text-xs text-secondary">{label}</div> : null
    }

    return <PayloadPermissionEvidence label={label} payload={payload} />
}

/** A decline that relays feedback is answered through its inline textarea, not a plain click. */
function isFeedbackOption(option: ApprovalCardOption): boolean {
    return option.requiresFeedback || option.supportsFeedback
}

function optionRowLabel(option: ApprovalCardOption): string {
    // The wire's feedback option describes the interaction ("Type here to tell the agent…") instead of
    // naming the choice; the textarea placeholder carries that instruction, the row just needs a name.
    if (isFeedbackOption(option) && /^type here\b/i.test(option.label)) {
        return 'Do it differently…'
    }
    return option.label
}

function optionSublabel(option: ApprovalCardOption): string | null {
    if (option.requiresFeedback) {
        return 'The agent adjusts and continues instead of stopping this turn.'
    }
    if (option.supportsFeedback) {
        return 'With a note the agent adjusts and continues. Without one, declining stops this turn.'
    }
    if (option.decision === 'declined') {
        return 'Stops this turn. Send a follow-up to redirect the agent.'
    }
    return null
}

interface PermissionOptionRowsProps {
    options: ApprovalCardOption[]
    responding: boolean
    onRespond: (optionId: string, customInput?: string) => void
}

function isEditableTarget(target: EventTarget | null): boolean {
    return (
        target instanceof HTMLElement &&
        (target.tagName === 'INPUT' ||
            target.tagName === 'TEXTAREA' ||
            target.tagName === 'SELECT' ||
            target.isContentEditable ||
            target.closest('[role="menu"]') !== null)
    )
}

function ignoresPermissionShortcut(
    event: KeyboardEvent,
    responding: boolean,
    container: HTMLDivElement | null
): boolean {
    const target = event.target
    return (
        event.defaultPrevented ||
        responding ||
        isEditableTarget(target) ||
        (target instanceof HTMLElement && target !== document.body && !container?.contains(target))
    )
}

interface PermissionShortcut {
    action: 'activate' | 'select'
    index: number
}

function numericShortcut(event: KeyboardEvent, optionsLength: number): PermissionShortcut | null {
    if (!/^[1-9]$/.test(event.key) || event.metaKey || event.ctrlKey) {
        return null
    }

    const index = Number.parseInt(event.key, 10) - 1
    return index < optionsLength ? { action: 'activate', index } : null
}

function permissionShortcut(
    event: KeyboardEvent,
    selectedIndex: number,
    optionsLength: number
): PermissionShortcut | null {
    switch (event.key) {
        case 'ArrowUp':
            return { action: 'select', index: (selectedIndex - 1 + optionsLength) % optionsLength }
        case 'ArrowDown':
            return { action: 'select', index: (selectedIndex + 1) % optionsLength }
        case 'Enter':
            return { action: 'activate', index: selectedIndex }
        default:
            return numericShortcut(event, optionsLength)
    }
}

interface PermissionOptionRowProps {
    feedback: string
    hovered: boolean
    index: number
    onActivate: (index: number) => void
    onFeedbackChange: (feedback: string) => void
    onResetFeedback: () => void
    onSelect: (index: number) => void
    option: ApprovalCardOption
    optionsLength: number
    responding: boolean
    selected: boolean
    onSubmitFeedback: (option: ApprovalCardOption) => void
    setHoveredIndex: (index: number | null) => void
}

function optionRowClass(selected: boolean, hovered: boolean): string {
    if (selected) {
        return 'bg-accent-highlight-secondary'
    }
    if (hovered) {
        return 'bg-fill-button-tertiary-hover'
    }
    return 'bg-transparent'
}

function PermissionOptionRow({
    feedback,
    hovered,
    index,
    onActivate,
    onFeedbackChange,
    onResetFeedback,
    onSelect,
    option,
    optionsLength,
    responding,
    selected,
    onSubmitFeedback,
    setHoveredIndex,
}: PermissionOptionRowProps): JSX.Element {
    const active = selected || hovered
    const editing = isFeedbackOption(option) && selected
    const sublabel = optionSublabel(option)

    return (
        <div
            onClick={() => onActivate(index)}
            onMouseEnter={() => setHoveredIndex(index)}
            onMouseLeave={() => setHoveredIndex(null)}
            className={cn('-mx-3 cursor-pointer select-none rounded px-3 py-1', optionRowClass(selected, hovered))}
        >
            <div className="flex items-center gap-2 leading-4">
                <span className={cn('w-[1ch] shrink-0 text-[13px] leading-4', selected ? 'text-accent' : 'text-muted')}>
                    {selected ? '›' : ''}
                </span>
                <span
                    className={cn(
                        'min-w-4 shrink-0 whitespace-nowrap text-right text-[13px] leading-4',
                        active ? 'text-accent' : 'text-muted'
                    )}
                >
                    {index + 1}.
                </span>
                <div className="min-w-0 flex-1 leading-4">
                    {editing ? (
                        <InlineEditableText
                            value={feedback}
                            placeholder={FEEDBACK_PLACEHOLDER}
                            active={editing}
                            disabled={responding}
                            onChange={onFeedbackChange}
                            onNavigateUp={() => onSelect((index - 1 + optionsLength) % optionsLength)}
                            onNavigateDown={() => onSelect((index + 1) % optionsLength)}
                            onEscape={onResetFeedback}
                            onSubmit={() => onSubmitFeedback(option)}
                        />
                    ) : (
                        <span
                            className={cn(
                                'whitespace-pre-wrap font-medium text-[13px] leading-4',
                                active ? 'text-accent' : 'text-primary'
                            )}
                        >
                            {optionRowLabel(option)}
                        </span>
                    )}
                </div>
            </div>
            {sublabel && <p className="mt-0.5 mb-0 pl-10 text-xs text-muted">{sublabel}</p>}
        </div>
    )
}

/**
 * The generic approval's option rows, in the same CLI-like grammar as `PlanApprovalSelector`: caret +
 * numbered rows, window-level ↑↓/Enter/digit shortcuts, and an inline feedback textarea for a decline
 * that relays a note. Activating an approve or plain-decline row answers immediately; activating a
 * feedback-capable decline opens its textarea (Enter sends; for the optional-feedback kind an empty
 * Enter is the plain decline, for the legacy feedback-only kind it is a no-op). Consequence copy is a
 * sublabel on the row it applies to, shown while that row is selected or hovered.
 */
function PermissionOptionRows({ options, responding, onRespond }: PermissionOptionRowsProps): JSX.Element {
    const [selectedIndex, setSelectedIndex] = useState(0)
    const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
    const [feedback, setFeedback] = useState('')
    const containerRef = useRef<HTMLDivElement>(null)

    const selectRow = (index: number): void => {
        setHoveredIndex(null)
        setSelectedIndex(index)
    }

    const activate = (index: number): void => {
        const option = options[index]
        if (!option || responding) {
            return
        }
        if (isFeedbackOption(option)) {
            selectRow(index)
            return
        }
        onRespond(option.optionId)
    }

    const submitFeedback = (option: ApprovalCardOption): void => {
        if (responding) {
            return
        }
        const text = feedback.trim()
        // The legacy feedback-only decline needs text on the wire; an empty Enter is a no-op. The
        // optional-feedback decline stays answerable without a note — that IS the plain decline.
        if (option.requiresFeedback && !text) {
            return
        }
        onRespond(option.optionId, text || undefined)
    }

    // Window-level shortcuts mirroring PlanApprovalSelector's guards: the feedback textarea owns the
    // keyboard while its row is selected, form fields and open menus are left alone, and focus resting
    // on an element outside the card keeps its native keys.
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent): void => {
            if (ignoresPermissionShortcut(e, responding, containerRef.current)) {
                return
            }
            const shortcut = permissionShortcut(e, selectedIndex, options.length)
            if (!shortcut) {
                return
            }

            e.preventDefault()
            if (shortcut.action === 'select') {
                selectRow(shortcut.index)
            } else {
                activate(shortcut.index)
            }
        }

        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    })

    return (
        <div ref={containerRef} className="flex flex-col gap-1 px-2">
            {options.map((option, index) => (
                <PermissionOptionRow
                    key={option.optionId}
                    feedback={feedback}
                    hovered={hoveredIndex === index}
                    index={index}
                    onActivate={activate}
                    onFeedbackChange={setFeedback}
                    onResetFeedback={() => {
                        setFeedback('')
                        selectRow(0)
                    }}
                    onSelect={selectRow}
                    option={option}
                    optionsLength={options.length}
                    responding={responding}
                    selected={selectedIndex === index}
                    onSubmitFeedback={submitFeedback}
                    setHoveredIndex={setHoveredIndex}
                />
            ))}
        </div>
    )
}

interface PermissionOptions {
    mappedOptions: ApprovalCardOption[]
    planApproveOptions: ApprovalCardOption[]
    planOptions: ApprovalCardOption[]
}

function getPermissionOptions(request: PermissionRequestRecord): PermissionOptions {
    // A plan approval keeps the product's Auto and Full auto wire options. If neither is offered,
    // fall through to the generic card so the request stays actionable.
    const planOptions = isPlanPermissionRequest(request) ? mapPermissionOptions(request.options, true) : []
    const planApproveOptions = planOptions.filter(
        (option) => option.decision === 'approved' && isPlanApprovalModeOptionId(option.optionId)
    )

    // A request whose every option was filtered out (e.g. only `allow_always` without a rememberable
    // preview) must still be answerable — fall back to showing everything. A plan that fell through
    // (unrecognized mode ids) keeps its unfiltered options: its approve choices are `allow_always`-kind
    // and the default filtering would leave a decline-only card.
    const defaultOptions = planOptions.length > 0 ? planOptions : mapPermissionOptions(request.options)
    const mappedOptions = defaultOptions.length > 0 ? defaultOptions : mapPermissionOptions(request.options, true)

    return { mappedOptions, planApproveOptions, planOptions }
}

interface PlanPermissionInputProps {
    approveOptions: ApprovalCardOption[]
    rejectOption?: ApprovalCardOption
    responding: boolean
    onCancel: () => void
    onRespond: (optionId: string, customInput?: string) => void
}

function PlanPermissionInput({
    approveOptions,
    rejectOption,
    responding,
    onCancel,
    onRespond,
}: PlanPermissionInputProps): JSX.Element {
    return (
        <div className="p-3">
            <PlanApprovalSelector
                approveOptions={approveOptions}
                rejectOption={rejectOption}
                responding={responding}
                onApprove={(optionId) => onRespond(optionId)}
                onReject={(optionId, feedback) => onRespond(optionId, feedback)}
                onCancel={onCancel}
            />
        </div>
    )
}

interface GenericPermissionInputProps {
    options: ApprovalCardOption[]
    request: PermissionRequestRecord
    responding: boolean
    onRespond: (optionId: string, customInput?: string) => void
}

function GenericPermissionInput({ options, request, responding, onRespond }: GenericPermissionInputProps): JSX.Element {
    const display = getPermissionDisplay(request)
    // Only a genuine wire-level description that says more than the tool title becomes the
    // headline; a title-only request keeps the derived tool title as its headline (and the
    // evidence block skips its label) so the tool identity is stated exactly once.
    const headlineBody = request.description && request.description !== display.title ? request.description : undefined

    // A product may register a richer approval preview (e.g. a config diff) for the resolved sub-tool
    // via the tool registry. When it returns a node, it takes the evidence slot; a null return (or a
    // throwing preview, or no registered preview) falls back to the generic evidence block.
    const previewNode = renderRegisteredPermissionPreview(request)

    return (
        <div className="flex flex-col gap-2.5 p-3">
            <div className="flex items-start gap-2 text-sm font-medium">
                <IconWarning className="text-warning size-4 mt-0.5 shrink-0" />
                {headlineBody ? (
                    <div className="max-h-60 overflow-y-auto min-w-0 flex-1">
                        <MarkdownMessage content={headlineBody} id={`permission-${request.requestId}`} />
                    </div>
                ) : (
                    <span>{display.title ?? 'Approval required'}</span>
                )}
            </div>
            {previewNode ? (
                <div className="max-h-80 overflow-y-auto">{previewNode}</div>
            ) : (
                <PermissionEvidence
                    request={request}
                    label={headlineBody ? display.title : undefined}
                    payload={display.payload}
                />
            )}
            <PermissionOptionRows options={options} responding={responding} onRespond={onRespond} />
        </div>
    )
}

/**
 * Self-contained input-area renderer for an ACP `permission_request` on a sandbox conversation.
 * A plan approval (`ExitPlanMode`) renders `/code`'s plan-approval selector (the plan itself is the
 * document card in the thread); every other request renders the one-voice approval card: a single
 * headline sentence (the request's description) with the warning icon inline, the evidence block
 * (diff or capped payload preview), and the option rows. `allow_always` stays hidden unless filtering
 * would leave no choices.
 *
 * Submitting POSTs through `runStreamLogic.respondToPermission`; the logic's
 * `respondingToPermission` drives the loading/double-submit guard and re-enables the controls when the
 * POST fails (the pending request only clears on success).
 */
export function PermissionInput({ streamKey, request, disabled = false }: PermissionInputProps): JSX.Element {
    const boundLogic = runStreamLogic({ streamKey })
    const { respondToPermission, cancelRun } = useActions(boundLogic)
    const { respondingToPermission: delivering } = useValues(boundLogic)
    const respondingToPermission = delivering || disabled

    const { mappedOptions, planApproveOptions, planOptions } = getPermissionOptions(request)
    if (planApproveOptions.length > 0) {
        return (
            <PlanPermissionInput
                approveOptions={planApproveOptions}
                rejectOption={planOptions.find((option) => option.decision === 'declined')}
                responding={respondingToPermission}
                onCancel={cancelRun}
                onRespond={(optionId, customInput) =>
                    respondToPermission({ requestId: request.requestId, optionId, customInput })
                }
            />
        )
    }

    return (
        <GenericPermissionInput
            options={mappedOptions}
            request={request}
            responding={respondingToPermission}
            onRespond={(optionId, customInput) =>
                respondToPermission({ requestId: request.requestId, optionId, customInput })
            }
        />
    )
}
