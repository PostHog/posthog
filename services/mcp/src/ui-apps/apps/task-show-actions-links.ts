/**
 * Action shapes for the `task-show-actions` card. Each action is a typed verb
 * the host turns into a deep link, so the card never receives or builds a URL.
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
    actions: ShowAction[]
}
