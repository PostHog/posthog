import type { PermissionRequestRecord } from '../types/streamTypes'
import type { PermissionOption } from '../types/wireTypes'

/**
 * An `ExitPlanMode` approval — the plan-review card, not a generic tool approval. On the wire the
 * agent-server's plan request carries no top-level tool name and `kind: 'switch_mode'`; the reliable
 * signal is the `toolName` it embeds in the tool input (`rawInput: { plan, planFilePath, toolName }`).
 * The top-level name and `kind === 'plan'` cover adapters that tag the request directly.
 */
export function isPlanPermissionRequest(request: PermissionRequestRecord): boolean {
    return (
        request.toolName === 'ExitPlanMode' ||
        request.rawToolCall.input?.toolName === 'ExitPlanMode' ||
        request.rawToolCall.kind === 'plan'
    )
}

/**
 * The card-facing decision a user can take on a sandbox ACP `permission_request` option. The
 * sandbox runtime surfaces richer ACP option kinds that all map down onto approve / decline.
 */
export type ApprovalDecision = 'approved' | 'declined'

/**
 * One control the sandbox approval card renders, derived from an ACP `permission_request` option.
 * The card forwards `optionId` back verbatim on the `permission_response` — the kind only drives
 * the UI affordance and the resolution status recorded locally.
 */
export interface ApprovalCardOption {
    optionId: string
    label: string
    /** Resolution status the card records once this option is chosen. */
    decision: ApprovalDecision
    /** Primary CTA styling (the single `allow_once`/approve path). */
    primary: boolean
    /** `allow_always` — only shown when the tool preview opts in via `remember: true`. */
    remembered: boolean
    /** Legacy `reject_with_feedback` — actionable only through the feedback text input, never a plain button. */
    requiresFeedback: boolean
    /** `reject_once` carrying `_meta.customInput` — a one-click decline that ALSO offers an optional feedback input. */
    supportsFeedback: boolean
}

/**
 * Maps an ACP `permission_request` option onto the sandbox approval card's option model. The
 * affordance is resolved by prefix, not exact kind: `allow*` is an approval, everything else a
 * decline. This keeps adapter vocabulary drift (`reject` → `reject_once`, future renames) from
 * dropping options. `allow_always` is the one kind that needs exact matching — it drives the
 * rememberable hiding (hidden unless `allowRemember`; still returned, flagged via `remembered`).
 */
export function mapPermissionOption(option: PermissionOption): ApprovalCardOption {
    if (option.kind.startsWith('allow')) {
        const remembered = option.kind === 'allow_always'
        return {
            optionId: option.optionId,
            label: option.name || (remembered ? 'Approve always' : 'Approve'),
            decision: 'approved',
            primary: !remembered,
            remembered,
            requiresFeedback: false,
            supportsFeedback: false,
        }
    }

    // Decline. The legacy `reject_with_feedback` kind is feedback-only (no plain button); the current
    // adapter's `reject_once` stays a one-click decline and advertises optional feedback via
    // `_meta.customInput` (parsed onto `option.customInput`).
    const requiresFeedback = option.kind === 'reject_with_feedback'
    return {
        optionId: option.optionId,
        label: option.name || (requiresFeedback ? 'Decline with feedback…' : 'Decline'),
        decision: 'declined',
        primary: false,
        remembered: false,
        requiresFeedback,
        supportsFeedback: !requiresFeedback && option.customInput === true,
    }
}

/**
 * Maps the full ACP `options[]` to card options, dropping `allow_always` unless the tool preview
 * opted into a rememberable decision (`allowRemember`).
 */
export function mapPermissionOptions(
    options: PermissionOption[],
    allowRemember: boolean = false
): ApprovalCardOption[] {
    return options.map(mapPermissionOption).filter((option) => !option.remembered || allowRemember)
}
