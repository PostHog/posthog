import { inStorybookTestRunner } from 'lib/utils/dom'

import { AssistantMessage } from '~/queries/schema/schema-assistant-messages'

// Status words for a running turn. All hog, on purpose: a wait is one of the few
// moments a customer reads our copy word by word, so it may as well sound like us.
// `products/desktop/packages/core/src/sessions/thinkingActivities.ts` keeps the same
// list for PostHog Desktop — keep the two together.
export const THINKING_MESSAGES = [
    'Booping', // the classic snoot boop
    'Snuffling', // hedgehog for "searching"
    'Snouting', // nose first, as always
    'Snoutlining', // outlining, but with the nose
    'Snoutdiving', // straight into the data
    'Quilling', // growing a spike for this one
    'Requilling', // a lost quill grows back, so does a lost thought
    'Quillsharpening', // old tools, new answers
    'Quillcounting', // about 5,000 of them, one moment please
    'Quillcrafting', // building with our Quill design system
    'Bristling', // spikes up, work on
    'Prickling', // a hunch, with points
    'Pincushioning', // the problem now has holes in it
    'Curling', // spiky ball mode, for thinking
    'Unrolling', // the ball opens, the answer shows
    'Burrowing', // down through the stack
    'Rooting', // through the logs
    'Foraging', // for the one event that explains it
    'Rummaging', // untidy, but productive
    'Anointing', // hedgehogs self-anoint, we self-review
    'Arraying', // a group of hedgehogs is truly called an array
    'Purring', // the sound of a content hedgehog
    'Chirping', // a hedgehog with news
    'Scuttling', // short legs, high speed
    'Waddling', // not fast, but arriving
    'Trundling', // slow and sure
    'Brambling', // through the thorny part
    'Hedgerowing', // working along the hedge
    'Hedgeclipping', // cutting back the overgrowth
    'Topiarying', // giving the hedge a shape
    'Hedgemazing', // finding the way through
    'Hedgehugging', // careful, but warm
    'Leafpiling', // building a nest for the answer
    'Nesting', // structure first
    'Nightshifting', // hedgehogs work nights
    'Moonlighting', // a second shift, by moonlight
    'Wheelrunning', // a hedgehog runs kilometers each night
    'Hogletting', // small steps now, big hog later
    'Molehilling', // turning your mountain back into a molehill
    'Spelunking', // deep in the caves of your codebase
    'Mudlarking', // there is treasure in the mud
    'Trufflehunting', // hogs find the valuable part
    'Hedgehogging', // the most hedgehog thing possible
    'Posthogging', // brand pun, no apologies
    'Hedging', // hedgehog pun, kept from the old list
    'Hoggifying', // to make a thing more hog
    'Hog-easing', // smooth, like a good animation curve
    'Hogitating', // cogitating, with more snout
    'Hogorithming', // the algorithm, but hog
    'Hogothesizing', // forming a hypothesis
    'Hogtimizing', // making it faster
    'Hogstimating', // a hog's guess, honestly given
    'Hogsembling', // putting the parts together
    'Hogfactoring', // same behavior, better shape
    'Hogpiling', // every idea at once
    'Hogwarming', // warming the cache
    'Hogwrangling', // many hogs, one direction
    'Hogtrotting', // the hog trot: a working pace
    'Wholehogging', // going the whole hog
    'Hedgineering', // engineering, but spikier
    'Hedgeploying', // sending it out
    'Hogfooding', // we use PostHog on PostHog
    'Hogcasting', // telling everybody at once
    'Squeaking', // a small sound, a big question
    'Flagging', // feature flags, our favorite switch
    'Funneling', // step, then step, then step
    'Cohorting', // grouping your people
    'Sessionizing', // events become a session
    'Replaying', // watching it happen again
    'Autocapturing', // catching events you did not name
    'Dashboarding', // one page, many answers
    'Experimenting', // A, B, and a verdict
    'Instrumenting', // adding the measurement that was missing
    'Materializing', // like a materialized view, but for thoughts
    'HogQLing', // SQL, with a snout
    'Sandboxing', // this turn really does run in a sandbox
    'Warehousing', // moving the big data in
    'Pipelining', // data in, data out
    'Signaling', // signals pun
    'Self-driving', // autonomy pun
    'Surveying', // asking your users directly
    'Heatmapping', // where the clicks are
    'Symbolicating', // turning a stack trace into names
    'Backfilling', // filling in yesterday
    'Deduping', // one of each is enough
    'Sharding', // many small parts, one whole
    'Batching', // all of it, in one go
    'Debouncing', // wait, then act
    'Linting', // small corrections, quietly
    'Compiling', // the slow, honest part
    'Migrating', // moving the schema forward
    'Rebasing', // history, tidied
    'Merging', // putting ideas together
    'Bisecting', // half of the history is innocent
    'Yakshaving', // the real task is three yaks down
    'Rubberducking', // explaining it to the hedgehog
    'Prototyping', // the fast, wrong first version
    'Shipping', // the point of all this
    'Untangling', // one thread at a time
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
