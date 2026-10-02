// Everything a hedgehog can see, say, or use in Club Hoguin.
// Chat is limited to the preset phrases and emotes below, so no player can type free text.

// The town is measured in units. x runs from west to east and y from north to south.
export const WORLD_WIDTH = 40
export const WORLD_DEPTH = 22

// Hedgehogs walk inside these bounds. The buildings stand north of the bounds, along the back of the town.
export const WALK_BOUNDS = { minX: 1, maxX: 39, minY: 5, maxY: 21 }
export const SPAWN = { x: 20, y: 15.5 }
export const WALK_SPEED = 7

export interface Rect {
    x: number
    y: number
    w: number
    h: number
}

export interface Ellipse {
    x: number
    y: number
    rx: number
    ry: number
}

export type Collider = ({ shape: 'rect' } & Rect) | ({ shape: 'ellipse' } & Ellipse)

export type ObjectId = 'flag' | 'replay' | 'max' | 'bugs' | 'door-a' | 'door-b' | 'ship'

export interface WorldObject {
    id: ObjectId
    name: string
    product: string
    // What a hedgehog does here. Clients show it before the hedgehog uses the object.
    hint: string
    glyph: string
    color: string
    // The ground the object covers.
    footprint: Rect
    // Where a hedgehog stands to use the object.
    stand: { x: number; y: number }
}

export const OBJECTS: readonly WorldObject[] = [
    {
        id: 'flag',
        name: 'Feature flag lighthouse',
        product: 'Feature flags',
        hint: 'Pull the lever to flip night-mode for everyone',
        glyph: 'F',
        color: '#F9BD2B',
        footprint: { x: 2, y: 1, w: 4.5, h: 3.5 },
        stand: { x: 6.4, y: 5.7 },
    },
    {
        id: 'replay',
        name: 'Replay cinema',
        product: 'Session replay',
        hint: 'Start the next session replay on the big screen',
        glyph: 'R',
        color: '#1D4AFF',
        footprint: { x: 8.5, y: 0.5, w: 10, h: 4 },
        stand: { x: 13.5, y: 5.7 },
    },
    {
        id: 'door-a',
        name: 'Door A',
        product: 'Experiments',
        hint: 'Walk through door A to vote for it in the experiment',
        glyph: 'A',
        color: '#30ABC6',
        footprint: { x: 22.3, y: 3.5, w: 2, h: 1 },
        stand: { x: 23.3, y: 5.5 },
    },
    {
        id: 'door-b',
        name: 'Door B',
        product: 'Experiments',
        hint: 'Walk through door B to vote for it in the experiment',
        glyph: 'B',
        color: '#F54E00',
        footprint: { x: 25.7, y: 3.5, w: 2, h: 1 },
        stand: { x: 26.7, y: 5.5 },
    },
    {
        id: 'max',
        name: "Max's desk",
        product: 'PostHog AI',
        hint: 'Ask Max for a joke',
        glyph: 'M',
        color: '#B62AD9',
        footprint: { x: 32, y: 1, w: 6, h: 3.5 },
        stand: { x: 35, y: 5.7 },
    },
    {
        id: 'bugs',
        name: 'Bug jar',
        product: 'Error tracking',
        hint: 'Catch a bug and put it in the jar',
        glyph: 'E',
        color: '#F54E00',
        footprint: { x: 4, y: 14.5, w: 2.6, h: 2.2 },
        stand: { x: 5.3, y: 18 },
    },
    {
        id: 'ship',
        name: 'Ship it button',
        product: 'Product analytics',
        hint: 'Press the button to ship to production',
        glyph: 'S',
        color: '#2BA84A',
        footprint: { x: 32, y: 13.5, w: 4, h: 3.2 },
        stand: { x: 34, y: 18 },
    },
]

// The experiments lab is one building. Its two doors are separate objects in OBJECTS.
export const LAB_FOOTPRINT: Rect = { x: 21, y: 1, w: 8, h: 3.5 }
export const POND: Ellipse = { x: 11, y: 10.6, rx: 4.2, ry: 2.5 }
export const CAMPFIRE: Ellipse = { x: 20, y: 11.5, rx: 1.3, ry: 1.3 }

export interface Decoration {
    kind: 'bench' | 'snowman' | 'tree' | 'signpost'
    x: number
    y: number
    radius: number
}

// Things in the square that hedgehogs walk around but cannot use.
export const DECORATIONS: readonly Decoration[] = [
    { kind: 'bench', x: 16.4, y: 11.5, radius: 0.8 },
    { kind: 'bench', x: 23.6, y: 11.5, radius: 0.8 },
    { kind: 'snowman', x: 14.6, y: 18.2, radius: 0.8 },
    { kind: 'tree', x: 28.6, y: 10.2, radius: 0.7 },
    { kind: 'tree', x: 2.6, y: 9.6, radius: 0.7 },
    { kind: 'tree', x: 37.4, y: 9.4, radius: 0.7 },
    { kind: 'signpost', x: 25.4, y: 18.6, radius: 0.45 },
]

// Where a hedgehog cannot walk. The buildings need no entry, because they stand outside WALK_BOUNDS.
export const COLLIDERS: readonly Collider[] = [
    { shape: 'ellipse', ...POND },
    { shape: 'ellipse', ...CAMPFIRE },
    ...DECORATIONS.map(({ x, y, radius }): Collider => ({ shape: 'ellipse', x, y, rx: radius, ry: radius })),
    ...OBJECTS.filter((object) => object.footprint.y >= WALK_BOUNDS.minY).map(
        (object): Collider => ({ shape: 'rect', ...object.footprint })
    ),
]

export function isInsideEllipse(ellipse: Ellipse, x: number, y: number, margin = 0): boolean {
    return ((x - ellipse.x) / (ellipse.rx + margin)) ** 2 + ((y - ellipse.y) / (ellipse.ry + margin)) ** 2 <= 1
}

export function isInsideRect(rect: Rect, x: number, y: number, margin = 0): boolean {
    return (
        x >= rect.x - margin && x <= rect.x + rect.w + margin && y >= rect.y - margin && y <= rect.y + rect.h + margin
    )
}

// A map of text characters for clients that draw in a terminal. A terminal cell is about twice as tall
// as it is wide, so one character covers 1 unit from west to east and 2 units from north to south.
export const TEXT_MAP_UNITS_PER_ROW = 2
export const WALL = '#'
export const WATER = '~'
export const FIRE = '^'

function textMapCell(x: number, y: number): string {
    if (isInsideRect(LAB_FOOTPRINT, x, y)) {
        const door = OBJECTS.find(
            ({ id, footprint }) => id.startsWith('door-') && x >= footprint.x && x <= footprint.x + footprint.w
        )
        return door ? door.glyph : WALL
    }
    const object = OBJECTS.find(({ footprint }) => isInsideRect(footprint, x, y))
    if (object) {
        return object.glyph
    }
    if (x < WALK_BOUNDS.minX || x > WALK_BOUNDS.maxX || y < WALK_BOUNDS.minY - 1 || y > WALK_BOUNDS.maxY) {
        return WALL
    }
    if (isInsideEllipse(POND, x, y)) {
        return WATER
    }
    return isInsideEllipse(CAMPFIRE, x, y) ? FIRE : '.'
}

export const TEXT_MAP_ROWS: readonly string[] = Array.from(
    { length: WORLD_DEPTH / TEXT_MAP_UNITS_PER_ROW },
    (_row, row) =>
        Array.from({ length: WORLD_WIDTH }, (_column, column) =>
            textMapCell(column + 0.5, row * TEXT_MAP_UNITS_PER_ROW + TEXT_MAP_UNITS_PER_ROW / 2)
        ).join('')
)

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

export interface Emote {
    id: string
    emoji: string
    label: string
}

export const EMOTES: readonly Emote[] = [
    { id: 'wave', emoji: '👋', label: 'Wave' },
    { id: 'heart', emoji: '❤️', label: 'Heart' },
    { id: 'laugh', emoji: '😂', label: 'Laugh' },
    { id: 'party', emoji: '🎉', label: 'Party' },
    { id: 'coffee', emoji: '☕', label: 'Coffee' },
    { id: 'think', emoji: '🤔', label: 'Thinking' },
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
    'A user rage-clicks a disabled button for a whole minute',
    'Someone reads the pricing page very, very slowly',
    'A checkout flow with seven "are you sure?" modals',
    'A hedgehog tries to close a cookie banner',
    'Someone opens 40 tabs and closes the wrong one',
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
    'My favorite cohort? Hedgehogs who clicked on me.',
]

export const EXPERIMENT_SIGNIFICANCE_VOTES = 30
