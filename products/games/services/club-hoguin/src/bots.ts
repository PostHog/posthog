// Hedgehogs that live in the town on their own, so it is never empty. Each has a personality that
// decides what it does and how often. They are quiet: all of them together say about one line a minute.
// They start when CLUB_HOGUIN_BOTS is set, and they count against the player cap like anyone else.
import { EMOTES, LOOKS, OBJECTS, type ObjectId, PHRASES, WALK_BOUNDS } from './content.ts'
import type { World } from './world.ts'

interface Personality {
    // What the hedgehog is called in the town. It hints at what it does.
    name: string
    look: { skin: (typeof LOOKS)[number]['skin']; hat: (typeof LOOKS)[number]['hat'] }
    // Seconds between two things the bot does, low and high.
    pace: [number, number]
    // How likely each kind of thing is, out of 1. The rest of the time the bot wanders.
    use: number
    say: number
    emote: number
    // The objects this bot likes to use, and the phrases and emotes it likes.
    objects: ObjectId[]
    phrases: string[]
    emotes: string[]
}

// Three is enough for a town that feels alive without feeling crowded.
const PERSONALITIES: readonly Personality[] = [
    {
        name: 'Turbo Deploy',
        look: { skin: 'default', hat: 'cap' },
        pace: [6, 18],
        use: 0.5,
        say: 0.08,
        emote: 0.1,
        objects: ['ship', 'ship', 'bugs'],
        phrases: ['ship', 'master'],
        emotes: ['party', 'salute'],
    },
    {
        name: 'Curious Cohort',
        look: { skin: 'robohog', hat: null },
        pace: [10, 30],
        use: 0.45,
        say: 0.08,
        emote: 0.05,
        objects: ['door-a', 'door-b', 'door-a', 'door-b', 'max'],
        phrases: ['significant', 'flag'],
        emotes: ['think'],
    },
    {
        name: 'Mellow Replay',
        look: { skin: 'default', hat: 'sunglasses' },
        pace: [12, 40],
        use: 0.3,
        say: 0.06,
        emote: 0.12,
        objects: ['replay', 'max'],
        phrases: ['replay', 'building'],
        emotes: ['laugh', 'heart'],
    },
    {
        name: 'Sleepy Burrow',
        look: { skin: 'hogzilla', hat: null },
        pace: [5, 14],
        use: 0.08,
        say: 0.04,
        emote: 0.06,
        objects: ['bugs', 'flag'],
        phrases: ['hi', 'quills'],
        emotes: ['wave', 'coffee'],
    },
    {
        name: 'Nocturnal Flag',
        look: { skin: 'default', hat: 'tophat' },
        pace: [20, 60],
        use: 0.35,
        say: 0.08,
        emote: 0.15,
        objects: ['flag', 'max', 'bugs'],
        phrases: ['machine', 'done'],
        emotes: ['hibernate', 'think'],
    },
]

export class Bots {
    private readonly world: World
    private readonly random: () => number
    private readonly bots: Array<{ token: string; personality: Personality; nextActionAt: number }> = []

    constructor(world: World, count: number, random: () => number) {
        this.world = world
        this.random = random
        for (let index = 0; index < count; index++) {
            const personality = PERSONALITIES[index % PERSONALITIES.length]!
            const joined = world.join(
                'web',
                `bot-${index % 5}`,
                0,
                personality.look.skin,
                personality.look.hat,
                personality.name,
                true
            )
            if (joined.ok) {
                this.bots.push({ token: joined.player.token, personality, nextActionAt: 0 })
            }
        }
    }

    tick(now: number): void {
        for (const bot of this.bots) {
            this.world.touch(bot.token, now)
            if (now < bot.nextActionAt) {
                continue
            }
            const { personality } = bot
            const [low, high] = personality.pace
            bot.nextActionAt = now + (low + this.random() * (high - low)) * 1000
            const roll = this.random()
            if (roll < personality.use) {
                this.world.walkToUse(bot.token, this.pick(personality.objects), now)
            } else if (roll < personality.use + personality.say) {
                this.world.say(bot.token, this.pick(personality.phrases), now)
            } else if (roll < personality.use + personality.say + personality.emote) {
                this.world.emote(bot.token, this.pick(personality.emotes), now)
            } else {
                this.world.moveTo(
                    bot.token,
                    WALK_BOUNDS.minX + this.random() * (WALK_BOUNDS.maxX - WALK_BOUNDS.minX),
                    WALK_BOUNDS.minY + this.random() * (WALK_BOUNDS.maxY - WALK_BOUNDS.minY),
                    now
                )
            }
        }
    }

    private pick<T>(items: readonly T[]): T {
        return items[Math.floor(this.random() * items.length) % items.length] as T
    }
}

// The lists above name phrases, emotes, and objects by id. A typo would be a silent no-op, so they are checked once.
for (const personality of PERSONALITIES) {
    for (const id of personality.phrases) {
        if (!PHRASES.some((phrase) => phrase.id === id)) {
            throw new Error(`bot ${personality.name}: unknown phrase ${id}`)
        }
    }
    for (const id of personality.emotes) {
        if (!EMOTES.some((emote) => emote.id === id)) {
            throw new Error(`bot ${personality.name}: unknown emote ${id}`)
        }
    }
    for (const id of personality.objects) {
        if (!OBJECTS.some((object) => object.id === id)) {
            throw new Error(`bot ${personality.name}: unknown object ${id}`)
        }
    }
}
