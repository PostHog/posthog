// Mirrors ReactionKey in products/founder_mode/backend/logic/cofounder_chat/schemas.py.
// The LLM picks one key per turn under constrained decoding, so it can never return a
// key not in this list. Add a new key in both files at once.
//
// CONVENTION (going forward): new keys are named after the GIF itself, not an abstract
// emotion. E.g. the "It's illegal for you to ask me that" GIF becomes `illegal`; a future
// "shocked Pikachu" GIF becomes `shocked_pikachu`. Description-based keys let us layer
// in more GIFs without re-debating semantic taxonomy. The first few keys here predate
// this convention — leave them as is until they're replaced.
//
// A key with an empty URL is a *valid* choice for the LLM but renders no GIF — useful when
// you want to keep the slot in the menu while waiting on a real GIF.
export type ReactionKey =
    | 'excited'
    | 'skeptical'
    | 'thinking'
    | 'satisfied'
    | 'dismissive'
    | 'illegal'
    | 'michael_no'
    | 'wtf'

// Direct media URLs — no API key needed. Stable as long as the source GIFs aren't deleted.
export const REACTION_GIFS: Record<ReactionKey, string> = {
    excited: 'https://media.giphy.com/media/89x4osEodHEoo/giphy.gif', // "Awesome"
    skeptical: 'https://media.giphy.com/media/ANbD1CCdA3iI8/giphy.gif', // "Skeptical Fry (Futurama)"
    thinking: 'https://media.giphy.com/media/WRQBXSCnEFJIuxktnw/giphy.gif', // "Confused calculations"
    satisfied: 'https://media.giphy.com/media/Dy6KtvPNfNVAIEx7O6/giphy.gif', // "Happy smiling guy"
    dismissive: 'https://media.giphy.com/media/xFnM1NeZZtvvUlVV5E/giphy.gif', // "I'm so sick of this"
    illegal: 'https://media.giphy.com/media/wViyKj8pL7BwXyDt7A/giphy.gif', // "It's illegal for you to ask me that"
    michael_no: 'https://media.giphy.com/media/JYZ397GsFrFtu/giphy.gif', // "Michael Scott (Office) yelling NOOO"
    wtf: 'https://media.giphy.com/media/ukGm72ZLZvYfS/giphy.gif', // "wtf"
    // Unassigned alternates (drop into a slot above when you swap):
    // https://media.giphy.com/media/RILsqUte1MME7TzQJ9/giphy.gif — "um what"
}

// TEMP: globally disable GIF rendering without touching the catalog or call sites.
// Flip back to `false` (or remove this constant) to re-enable.
const REACTIONS_DISABLED = true

export function reactionGifUrl(key: ReactionKey | null | undefined): string | null {
    if (REACTIONS_DISABLED) {
        return null
    }
    if (!key) {
        return null
    }
    const url = REACTION_GIFS[key]
    return url || null
}
