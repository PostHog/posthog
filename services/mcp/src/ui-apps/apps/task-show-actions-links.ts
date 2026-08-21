/**
 * Action shapes for the `task-show-actions` card.
 *
 * The card never receives or builds a URL. Each action is a typed verb, and the
 * host turns it into a deep link for the scheme its own build registered, so a
 * tool call — including one an agent made after reading untrusted page text —
 * cannot hand the host an arbitrary URL to open.
 */

export interface ComposeAction {
    kind: 'compose'
    label: string
    prompt: string
    repo?: string
}

export interface OpenSpaceAction {
    kind: 'open_space'
    label: string
    channel_id: string
}

export interface OpenCanvasAction {
    kind: 'open_canvas'
    label: string
    channel_id: string
    canvas_id: string
}

export type ShowAction = ComposeAction | OpenSpaceAction | OpenCanvasAction

export interface ShowActionsData {
    actions?: ShowAction[]
    _posthogUrl?: string
}
