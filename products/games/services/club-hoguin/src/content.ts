// Everything a hedgehog can see, say, or poke in Club Hoguin.
// Chat is limited to the preset phrases below, so no player can type free text.

export const MAP_ROWS: readonly string[] = [
    '########################################',
    '#......................................#',
    '#......................................#',
    '#......................................#',
    '#......................................#',
    '#.......~~~~...........................#',
    '#......~~~~~~..........................#',
    '#......~~~~~~..........................#',
    '#.......~~~~...........................#',
    '#......................................#',
    '#......................................#',
    '#......................................#',
    '#......................................#',
    '#......................................#',
    '#......................................#',
    '########################################',
]

export const MAP_WIDTH = 40
export const MAP_HEIGHT = 16
export const SPAWN = { x: 20, y: 9 }

export const WALL = '#'
export const WATER = '~'

export type ObjectId = 'flag' | 'replay' | 'max' | 'bugs' | 'door-a' | 'door-b' | 'ship'

export interface WorldObject {
    id: ObjectId
    name: string
    product: string
    glyph: string
    color: string
    x: number
    y: number
    w: number
    h: number
}

export const OBJECTS: readonly WorldObject[] = [
    {
        id: 'flag',
        name: 'Feature flag lever',
        product: 'Feature flags',
        glyph: 'F',
        color: '#F9BD2B',
        x: 4,
        y: 2,
        w: 1,
        h: 2,
    },
    {
        id: 'replay',
        name: 'Replay cinema',
        product: 'Session replay',
        glyph: 'R',
        color: '#1D4AFF',
        x: 15,
        y: 1,
        w: 10,
        h: 2,
    },
    {
        id: 'max',
        name: "Max's desk",
        product: 'PostHog AI',
        glyph: 'M',
        color: '#B62AD9',
        x: 32,
        y: 2,
        w: 3,
        h: 2,
    },
    {
        id: 'bugs',
        name: 'Bug jar',
        product: 'Error tracking',
        glyph: 'E',
        color: '#F54E00',
        x: 4,
        y: 11,
        w: 2,
        h: 2,
    },
    {
        id: 'door-a',
        name: 'Door A',
        product: 'Experiments',
        glyph: 'A',
        color: '#30ABC6',
        x: 16,
        y: 14,
        w: 2,
        h: 1,
    },
    {
        id: 'door-b',
        name: 'Door B',
        product: 'Experiments',
        glyph: 'B',
        color: '#30ABC6',
        x: 22,
        y: 14,
        w: 2,
        h: 1,
    },
    {
        id: 'ship',
        name: 'Ship it button',
        product: 'Product analytics',
        glyph: 'S',
        color: '#2BA84A',
        x: 33,
        y: 11,
        w: 2,
        h: 2,
    },
]

export interface Phrase {
    id: string
    text: string
}

export const PHRASES: readonly Phrase[] = [
    { id: 'hi', text: 'Hi hogs! 👋' },
    { id: 'building', text: 'What are you building?' },
    { id: 'tests', text: 'My agent is running the tests 🧪' },
    { id: 'refactor', text: 'My agent is refactoring everything 😬' },
    { id: 'ship', text: 'Ship it! 🚀' },
    { id: 'flag', text: 'Have you tried a feature flag?' },
    { id: 'quills', text: 'Nice quills!' },
    { id: 'review', text: 'brb, reviewing a PR' },
    { id: 'done', text: 'gg, my agent is done 🎉' },
]

export const SKINS = ['default', 'spiderhog', 'robohog', 'hogzilla'] as const
export type Skin = (typeof SKINS)[number]

export const NAME_ADJECTIVES: readonly string[] = [
    'Spiky',
    'Curious',
    'Sleepy',
    'Speedy',
    'Funky',
    'Cozy',
    'Brave',
    'Sneaky',
    'Chill',
    'Bouncy',
    'Dapper',
    'Zesty',
    'Fuzzy',
    'Jolly',
    'Mellow',
    'Nimble',
    'Plucky',
    'Snug',
    'Sunny',
    'Witty',
]

export const NAME_NOUNS: readonly string[] = [
    'Hog',
    'Hoglet',
    'Quill',
    'Hedgineer',
    'Spike',
    'Prickle',
    'Snout',
    'Burrow',
    'Bramble',
    'Thistle',
    'Nettle',
    'Acorn',
]

// One name per adjective and noun pair. A full club needs at least LIMITS.maxPlayers of them.
export const NAMES: readonly string[] = NAME_ADJECTIVES.flatMap((adjective) =>
    NAME_NOUNS.map((noun) => `${adjective} ${noun}`)
)

export const REPLAY_REELS: readonly string[] = [
    'a user rage-clicking a disabled button for a whole minute',
    'someone reading the pricing page very, very slowly',
    'a checkout flow with seven "are you sure?" modals',
    'a hedgehog trying to close a cookie banner',
]

export const BUG_SPECIES: readonly string[] = [
    "TypeError: Cannot read properties of undefined (reading 'quills')",
    'RangeError: Maximum hedgehog depth exceeded',
    'ReferenceError: coffee is not defined',
    'SyntaxError: Unexpected token 🦔',
]

export const MAX_JOKES: readonly string[] = [
    'Why did the hedgehog cross the funnel? To get to the conversion step.',
    'I asked for a trend. It went up and to the right. You are welcome.',
    'Correlation is not causation. Unless it is an A/B test. Then it is science.',
    'I would tell you a joke about a retention curve, but you would not come back for it.',
]

export const EXPERIMENT_SIGNIFICANCE_VOTES = 30
