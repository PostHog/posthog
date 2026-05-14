// Mirrors ReactionKey in products/founder_mode/backend/logic/cofounder_chat/schemas.py.
// The LLM picks one key per turn under constrained decoding, so it can never return a
// key not in this list. Add a new posture in both files at once.
export type ReactionKey = 'excited' | 'skeptical' | 'thinking' | 'satisfied' | 'dismissive'

// The cofounder's posture per key:
// - excited: founder said something sharp; leaning in
// - skeptical: pushing back, naming a competitor, asking them to defend
// - thinking: probing (the most common turn)
// - satisfied: got it, wrapping
// - dismissive: vague/generic answer, refusing it
//
// Direct media URLs — no API key needed. Stable as long as the source GIFs aren't deleted.
// Alternates kept inline as comments for quick swaps without re-finding IDs.
export const REACTION_GIFS: Record<ReactionKey, string> = {
    excited: 'https://media.giphy.com/media/89x4osEodHEoo/giphy.gif', // "Awesome"
    skeptical: 'https://media.giphy.com/media/wViyKj8pL7BwXyDt7A/giphy.gif', // "It's illegal for you to ask me that"
    thinking: 'https://media.giphy.com/media/WRQBXSCnEFJIuxktnw/giphy.gif', // "Confused calculations"
    satisfied: 'https://media.giphy.com/media/Dy6KtvPNfNVAIEx7O6/giphy.gif', // "Happy smiling guy"
    dismissive: 'https://media.giphy.com/media/xFnM1NeZZtvvUlVV5E/giphy.gif', // "I'm so sick of this"
    // Alternate "um what" for skeptical / dismissive variety:
    // https://media.giphy.com/media/RILsqUte1MME7TzQJ9/giphy.gif
}

export function reactionGifUrl(key: ReactionKey | null | undefined): string | null {
    if (!key) {
        return null
    }
    const url = REACTION_GIFS[key]
    return url || null
}
