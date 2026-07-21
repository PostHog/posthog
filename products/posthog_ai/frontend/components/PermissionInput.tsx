import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import type { ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { Button, Spinner } from '@posthog/quill-primitives'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { cn } from 'lib/utils/css-classes'

import { runStreamLogic } from '../logics/runStreamLogic'
import { MarkdownMessage } from '../messages/MarkdownMessage'
import { getPermissionDisplay } from '../policy/permissionDisplayUtils'
import { isPlanPermissionRequest, mapPermissionOptions, type ApprovalCardOption } from '../policy/permissionUtils'
import type { PermissionRequestRecord } from '../types/streamTypes'
import { resolveToolCall } from '../utils/toolResolver'
import { isPlanApprovalModeOptionId, InlineEditableText, PlanApprovalSelector } from './PlanApprovalActions'
import { DiffEditor, DiffStats } from './tool/EditDiffRenderer'
import { FilePath } from './tool/FilePath'
import { findAllDiffContent, getDiffStats } from './tool/toolDiffContent'
import { lookupToolRenderer } from './tool/toolRegistry'

interface PermissionInputProps {
    streamKey: string
    request: PermissionRequestRecord
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

/**
 * The card's evidence block. A request whose tool call streamed `type: "diff"` content (Edit/Write, or
 * any adapter that reports a change to existing content) renders each diff with a path + stats header
 * and a side-by-side editor that collapses to unified when the container is narrow. Everything else
 * renders the payload preview capped at {@link PAYLOAD_COLLAPSED_LINES} with a "Show all" expander.
 */
function PermissionEvidence({ request, label, payload }: PermissionEvidenceProps): JSX.Element | null {
    const [showAll, setShowAll] = useState(false)
    const diffs = findAllDiffContent(request.rawToolCall.contentBlocks)

    if (diffs.length > 0) {
        return (
            <div className="flex flex-col gap-2 min-w-0">
                {diffs.map((diff, index) => {
                    const stats = getDiffStats(diff.oldText, diff.newText)
                    return (
                        <div key={index} className="flex flex-col gap-1 min-w-0">
                            <div className="flex items-center gap-2 min-w-0 text-xs text-secondary">
                                {diff.path ? (
                                    <FilePath path={diff.path} />
                                ) : (
                                    label && <span className="font-medium">{label}</span>
                                )}
                                <DiffStats added={stats.added} removed={stats.removed} />
                            </div>
                            <DiffEditor diff={diff} path={diff.path} sideBySide />
                        </div>
                    )
                })}
            </div>
        )
    }

    if (!payload) {
        return label ? <div className="text-xs text-secondary">{label}</div> : null
    }

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
            if (e.defaultPrevented || responding) {
                return
            }
            const target = e.target
            if (
                target instanceof HTMLElement &&
                (target.tagName === 'INPUT' ||
                    target.tagName === 'TEXTAREA' ||
                    target.tagName === 'SELECT' ||
                    target.isContentEditable ||
                    target.closest('[role="menu"]') !== null)
            ) {
                return
            }
            if (target instanceof HTMLElement && target !== document.body && !containerRef.current?.contains(target)) {
                return
            }
            switch (e.key) {
                case 'ArrowUp':
                    e.preventDefault()
                    selectRow((selectedIndex - 1 + options.length) % options.length)
                    break
                case 'ArrowDown':
                    e.preventDefault()
                    selectRow((selectedIndex + 1) % options.length)
                    break
                case 'Enter':
                    e.preventDefault()
                    activate(selectedIndex)
                    break
                default:
                    if (/^[1-9]$/.test(e.key) && !e.metaKey && !e.ctrlKey) {
                        const idx = Number.parseInt(e.key, 10) - 1
                        if (idx < options.length) {
                            e.preventDefault()
                            activate(idx)
                        }
                    }
            }
        }

        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    })

    return (
        <div ref={containerRef} className="flex flex-col gap-1 px-2">
            {options.map((option, index) => {
                const active = selectedIndex === index || hoveredIndex === index
                const editing = isFeedbackOption(option) && selectedIndex === index
                const sublabel = optionSublabel(option)
                const showSublabel = sublabel && (editing || active)
                return (
                    <div
                        key={option.optionId}
                        onClick={() => activate(index)}
                        onMouseEnter={() => setHoveredIndex(index)}
                        onMouseLeave={() => setHoveredIndex(null)}
                        className={cn(
                            '-mx-3 cursor-pointer select-none rounded px-3 py-1',
                            selectedIndex === index
                                ? 'bg-accent-highlight-secondary'
                                : hoveredIndex === index
                                  ? 'bg-fill-button-tertiary-hover'
                                  : 'bg-transparent'
                        )}
                    >
                        <div className="flex items-center gap-2 leading-4">
                            <span
                                className={cn(
                                    'w-[1ch] shrink-0 text-[13px] leading-4',
                                    selectedIndex === index ? 'text-accent' : 'text-muted'
                                )}
                            >
                                {selectedIndex === index ? '›' : ''}
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
                                        onChange={setFeedback}
                                        onNavigateUp={() => selectRow((index - 1 + options.length) % options.length)}
                                        onNavigateDown={() => selectRow((index + 1) % options.length)}
                                        onEscape={() => {
                                            setFeedback('')
                                            selectRow(0)
                                        }}
                                        onSubmit={() => submitFeedback(option)}
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
                        {showSublabel && <p className="mt-0.5 mb-0 pl-10 text-xs text-muted">{sublabel}</p>}
                    </div>
                )
            })}
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
export function PermissionInput({ streamKey, request }: PermissionInputProps): JSX.Element {
    const boundLogic = runStreamLogic({ streamKey })
    const { respondToPermission, cancelRun } = useActions(boundLogic)
    const { respondingToPermission } = useValues(boundLogic)

    // A plan approval keeps the product's Auto and Full auto wire options. If neither is offered,
    // fall through to the generic card so the request stays actionable.
    const planOptions = isPlanPermissionRequest(request) ? mapPermissionOptions(request.options, true) : []
    const planApproveOptions = planOptions.filter(
        (option) => option.decision === 'approved' && isPlanApprovalModeOptionId(option.optionId)
    )
    if (planApproveOptions.length > 0) {
        return (
            <div className="p-3">
                <PlanApprovalSelector
                    approveOptions={planApproveOptions}
                    rejectOption={planOptions.find((option) => option.decision === 'declined')}
                    responding={respondingToPermission}
                    onApprove={(optionId) => respondToPermission({ requestId: request.requestId, optionId })}
                    onReject={(optionId, feedback) =>
                        respondToPermission({ requestId: request.requestId, optionId, customInput: feedback })
                    }
                    onCancel={() => cancelRun()}
                />
            </div>
        )
    }

    // A request whose every option was filtered out (e.g. only `allow_always` without a rememberable
    // preview) must still be answerable — fall back to showing everything. A plan that fell through
    // (unrecognized mode ids) keeps its unfiltered options: its approve choices are `allow_always`-kind
    // and the default filtering would leave a decline-only card.
    const defaultOptions = planOptions.length > 0 ? planOptions : mapPermissionOptions(request.options)
    const mappedOptions = defaultOptions.length > 0 ? defaultOptions : mapPermissionOptions(request.options, true)

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
            {respondingToPermission ? (
                <div className="flex items-center gap-2 text-muted pt-1">
                    <Spinner className="size-4" />
                    <span>Sending response…</span>
                </div>
            ) : (
                <PermissionOptionRows
                    options={mappedOptions}
                    responding={respondingToPermission}
                    onRespond={(optionId, customInput) =>
                        respondToPermission({ requestId: request.requestId, optionId, customInput })
                    }
                />
            )}
        </div>
    )
}
