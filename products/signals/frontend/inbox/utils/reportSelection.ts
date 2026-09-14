/** How long a pointer must rest on a card before the hold selects it. */
export const SELECTION_HOLD_MS = 400

/** A hold that travels further than this is a scroll or a drag, so it never selects. */
export const SELECTION_HOLD_MOVE_TOLERANCE_PX = 8

/** What a click on a report row means. `open` follows the row's link to the report detail. */
export type ReportCardClickIntent = 'open' | 'toggle' | 'range'

/**
 * A plain click opens the report until something is selected; from then on the list is in
 * selection mode and the same click toggles instead. Cmd / Ctrl keeps browser navigation,
 * while shift selects a range, so a selection can start from an empty list.
 */
export function resolveReportCardClickIntent(
    modifiers: { shiftKey: boolean; metaKey: boolean; ctrlKey: boolean },
    hasSelection: boolean
): ReportCardClickIntent {
    if (modifiers.metaKey || modifiers.ctrlKey) {
        return 'open'
    }
    if (modifiers.shiftKey) {
        return 'range'
    }
    return hasSelection ? 'toggle' : 'open'
}

/** Controls a report row can nest inside its own link, such as the authoring scout's name. */
const ROW_CONTROL_SELECTOR = 'a, button, [role="button"], input, select, textarea'

/**
 * True when a click landed on a control nested inside the row's own link. The row's link is the
 * first control in the wrapper, so any other control is one the person aimed at directly.
 */
export function isNestedControlClick(target: EventTarget | null, wrapper: Element): boolean {
    if (!(target instanceof Element)) {
        return false
    }
    const clicked = target.closest(ROW_CONTROL_SELECTOR)
    return clicked !== null && clicked !== wrapper.querySelector(ROW_CONTROL_SELECTOR)
}

/** True while the keyboard is in a field, where Esc belongs to the field and not to the list. */
export function isTextEntryTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) {
        return false
    }
    if (target.isContentEditable || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
        return true
    }
    if (target instanceof HTMLInputElement) {
        return !['button', 'checkbox', 'color', 'file', 'radio', 'range', 'reset', 'submit'].includes(target.type)
    }
    return false
}
