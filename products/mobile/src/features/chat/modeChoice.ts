import type { ChatAgentMode } from '@/api/conversations'

/**
 * The server overwrites the checkpointed mode whenever a message carries `agent_mode`, which would undo a switch the
 * agent made on its own. So the chip state and the value to send are kept apart, and a pick goes out once.
 */
export interface ModeChoice {
    shown: ChatAgentMode | null
    pending: ChatAgentMode | null
    /** True after the first pick in this sheet, so a stored mode that loads late cannot replace it. */
    picked: boolean
}

export type ModeChoiceAction =
    | { type: 'seeded'; mode: ChatAgentMode | null }
    | { type: 'picked'; mode: ChatAgentMode | null }
    | { type: 'sent' }
    | { type: 'reset' }

export const initialModeChoice: ModeChoice = { shown: null, pending: null, picked: false }

export function modeChoiceReducer(state: ModeChoice, action: ModeChoiceAction): ModeChoice {
    switch (action.type) {
        case 'seeded':
            return state.picked || state.shown === action.mode ? state : { ...state, shown: action.mode }
        case 'picked':
            return { shown: action.mode, pending: action.mode, picked: true }
        case 'sent':
            return state.pending === null ? state : { ...state, pending: null }
        case 'reset':
            return initialModeChoice
    }
}
