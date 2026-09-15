import { inStorybookTestRunner } from 'lib/utils/dom'

import { AssistantMessage } from '~/queries/schema/schema-assistant-messages'

// Status words for a running turn. A wait is one of the few moments a customer reads
// our copy word by word, so most of these are about the hedgehog: what it eats, where
// it lives, how it moves, and the spines. The whimsical words that came before are
// kept below them.
// A new word earns its place by being funny on sight. If the joke needs trivia or a
// PostHog product noun to land, it is not a joke.
// `products/desktop/packages/core/src/sessions/thinkingActivities.ts` keeps the same
// list for PostHog Desktop — keep the two together.
export const THINKING_MESSAGES = [
    'Booping', // the classic snoot boop
    'Snouting', // nose first, as always
    'Snoutlining', // outlining, but with the nose
    'Snoutdiving', // straight in, snout first
    'Snoutwiggling', // the snout is working on it
    'Whiskering', // feeling out the edges
    'Quilling', // growing a spike for this one
    'Requilling', // a lost quill grows back, so does a lost thought
    'Quillsharpening', // the tools before the work
    'Quillcounting', // about 5,000 of them, one moment please
    'Quillpolishing', // presentation matters
    'Quillrustling', // the sound of a hedgehog with a plan
    'Bristling', // spikes up, work on
    'Prickling', // a hunch, with points
    'Spiking', // spines, not charts
    'Spinetingling', // this one is exciting
    'Pincushioning', // the problem now has holes in it
    'Curling', // spiky ball mode, for thinking
    'Unrolling', // the ball opens, the answer shows
    'Unfurling', // opening up, slowly
    'Snuffling', // hedgehog for "searching"
    'Sniffing', // following the smell of a bug
    'Nosing', // into places a hedgehog should not be
    'Rooting', // through the leaf litter
    'Foraging', // for the one useful thing
    'Rummaging', // untidy, but productive
    'Grubbing', // hunting grubs, and clues
    'Prowling', // the garden at 3am
    'Earwigging', // earwigs are food, gossip is data
    'Trufflehunting', // hogs find the valuable part
    'Beetlecrunching', // a hedgehog eats loudly
    'Slugsnaffling', // the garden says thank you
    'Snailsnuffling', // slow food
    'Wormwrangling', // they wriggle, we persist
    'Munching', // steady progress
    'Nibbling', // small bites of a big problem
    'Slurping', // no manners, good results
    'Lapping', // from the saucer
    'Saucersipping', // water, never milk: a real hedgehog rule
    'Puddlesipping', // a drink on the way
    'Scuttling', // short legs, high speed
    'Scurrying', // faster than it looks
    'Scampering', // enthusiasm over elegance
    'Waddling', // not fast, but arriving
    'Trundling', // slow and sure
    'Pattering', // tiny feet, real distance
    'Tiptoeing', // quietly, past the sleeping parts
    'Pawpadding', // four paws, one purpose
    'Earflicking', // heard something
    'Hedgehopping', // over one hedge, then the next
    'Hedgerowing', // working along the hedge
    'Hedgeclipping', // cutting back the overgrowth
    'Hedgemazing', // finding the way through
    'Hedgehugging', // careful, but warm
    'Brambling', // through the thorny part
    'Bushwhacking', // no path, going anyway
    'Leafpiling', // building a nest for the answer
    'Leafshuffling', // the classic hedgehog sound
    'Leafrustling', // something is happening in there
    'Compostdiving', // a hedgehog's favorite heap
    'Molehilling', // turning your mountain back into a molehill
    'Mudlarking', // there is treasure in the mud
    'Nesting', // structure first
    'Burrowing', // down and in
    'Nightshifting', // hedgehogs work nights
    'Moonlighting', // a second shift, by moonlight
    'Wheelrunning', // a hedgehog runs kilometers each night
    'Anointing', // hedgehogs self-anoint, we self-review
    'Squeaking', // a small sound, a big question
    'Chirping', // a hedgehog with news
    'Purring', // the sound of a content hedgehog
    'Hogletting', // small steps now, big hog later
    'Hedgehogging', // the most hedgehog thing possible
    'Posthogging', // brand pun, no apologies
    'Hedging', // hedgehog pun, kept from the old list
    'Hoggifying', // to make a thing more hog
    'Hogteasing', // a hog take on teasing
    'Hogitating', // cogitating, with more snout
    'Hogothesizing', // forming a hypothesis
    'Hogtimizing', // making it faster
    'Hogstimating', // a hog's guess, honestly given
    'Hogsembling', // putting the parts together
    'Hogfactoring', // same behavior, better shape
    'Hogpiling', // every idea at once
    'Hogwarming', // warming up
    'Hogwrangling', // many hogs, one direction
    'Hogtrotting', // the hog trot: a working pace
    'Wholehogging', // going the whole hog
    'Hedgineering', // engineering, but spikier
    'Hogorithming', // the algorithm, but hog
    'Piggybacking', // standing on the last good answer
    'Oinking', // the other kind of hog
    'Grunting', // the effort is audible
    'Hogswaggling', // hoggish bamboozling
    'Spelunking', // deep in the burrow
    'Hedgewatching', // waiting for a hedgehog to appear
    'Hogletherding', // many small ideas, one direction
    'Wormcharming', // a real sport, and a real skill
    'Cricketchasing', // it went that way

    // Kept from the list these replaced.
    'Digging', // going deep
    'Peeking', // quick look
    'Poking', // testing ideas
    'Snooping', // poking around data
    'Noodling', // casual problem-solving
    'Percolating', // slow thinking
    'Pondering', // thoughtful pause
    'Mulling', // slow consideration
    'Puzzling', // solving something tricky
    'Grokking', // deep understanding
    'Scheming', // clever planning
    'Swizzling', // techy weirdness
    'Tinkering', // tweaking stuff
    'Unraveling', // breaking things down
    'Dissecting', // breaking it apart
    'Sifting', // sorting signal from noise
    'Scrambling', // chaotic progress
    'Cranking', // pushing through work
    'Trekking', // on a journey
    'Hunting', // focused seeking
    'Scouting', // looking ahead
    'Scouring', // intense searching
    'Surfacing', // bringing something up
    'Snagging', // quick retrieval
    'Teasing', // nudging out meaning
    'Tickling', // triggering results lightly
    'Twinkling', // flicker of insight
    'Blooming', // ideas forming
    'Sparking', // fresh thought forming
    'Self-driving', // autonomy pun
    'Signaling', // signals pun
    'Flibbertigibbeting', // flustered but active chaos
    'Kerfuffling', // low-stakes commotion
    'Dithering', // indecisive processing
    'Discombobulating', // intentionally confused
    'Rambling', // aimless but possibly insightful
    'Befuddling', // trying to untangle confusion
    'Waffling', // bouncing between options
    'Muckling', // clinging onto something
    'Hobnobbing', // talking to the data gods
    'Galumphing', // awkward progress
    'Puttering', // low-energy thinking
    'Whiffling', // light, directionless searching

    'Thinking', // just thinking, like in the old days
]

export const getRandomThinkingMessage = (): string => {
    if (inStorybookTestRunner()) {
        return 'Thinking...'
    }
    const randomIndex = Math.floor(Math.random() * THINKING_MESSAGES.length)
    return THINKING_MESSAGES[randomIndex] + '...'
}

interface ServerToolUseBlock {
    type: 'server_tool_use'
    name: string
    input: Record<string, unknown>
    id: string
    results?: { title: string; url: string }[]
}

interface ThinkingBlock {
    type: 'thinking'
    thinking: string
}

export const getThinkingMessageFromResponse = (message: AssistantMessage): (ServerToolUseBlock | ThinkingBlock)[] => {
    const thinkingMeta = message.meta?.thinking
    if (!thinkingMeta) {
        return []
    }
    const blocks: (ServerToolUseBlock | ThinkingBlock)[] = []
    const toolUseIdToBlock: Record<string, ServerToolUseBlock> = {}
    for (const block of thinkingMeta) {
        if (block.type === 'thinking') {
            blocks.push({ type: 'thinking', thinking: block.thinking as string })
        } else if (block.type === 'server_tool_use') {
            toolUseIdToBlock[block.id as string] = {
                id: block.id as string,
                type: 'server_tool_use',
                name: block.name as string,
                input: block.input as Record<string, unknown>,
            }
            blocks.push(toolUseIdToBlock[block.id as string])
        } else if (block.type === 'web_search_tool_result') {
            if (!Array.isArray(block.content)) {
                console.error('web_search_tool_result is not an array', block)
                continue // Making TypeScript happy
            }
            if (!toolUseIdToBlock[block.tool_use_id as string]) {
                console.error(
                    'tool_use_id not found - likely web_search was called in parallel with another tool',
                    block,
                    toolUseIdToBlock
                )
                continue
            }
            toolUseIdToBlock[block.tool_use_id as string].results = block.content.map((content) => ({
                title: content.title as string,
                url: content.url as string,
            }))
        } else if (block.type === 'reasoning') {
            // OpenAI
            blocks.push({ type: 'thinking', thinking: (block.summary as any[])[0].text as string })
        }
    }
    return blocks
}
