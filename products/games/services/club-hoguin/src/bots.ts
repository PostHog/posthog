// Hedgehogs that walk around, chat, and use things on their own, so a town is never empty while you try it.
// They start when CLUB_HOGUIN_BOTS is set. They count against the player cap like anyone else.
import { EMOTES, LOOKS, OBJECTS, PHRASES, WALK_BOUNDS } from './content.ts'
import type { World } from './world.ts'

export class Bots {
    private readonly world: World
    private readonly random: () => number
    private readonly tokens: string[] = []
    private readonly nextActionAt = new Map<string, number>()

    constructor(world: World, count: number, random: () => number) {
        this.world = world
        this.random = random
        for (let index = 0; index < count; index++) {
            const look = LOOKS[Math.floor(random() * LOOKS.length)]!
            const joined = world.join('web', `bot-${index % 5}`, 0, look.skin, look.hat)
            if (joined.ok) {
                this.tokens.push(joined.player.token)
            }
        }
    }

    tick(now: number): void {
        for (const token of this.tokens) {
            this.world.touch(token, now)
            if (now < (this.nextActionAt.get(token) ?? 0)) {
                continue
            }
            this.nextActionAt.set(token, now + 2_000 + this.random() * 5_000)
            const roll = this.random()
            if (roll < 0.5) {
                this.world.moveTo(
                    token,
                    WALK_BOUNDS.minX + this.random() * (WALK_BOUNDS.maxX - WALK_BOUNDS.minX),
                    WALK_BOUNDS.minY + this.random() * (WALK_BOUNDS.maxY - WALK_BOUNDS.minY),
                    now
                )
            } else if (roll < 0.65) {
                this.world.walkToUse(token, OBJECTS[Math.floor(this.random() * OBJECTS.length)]!.id, now)
            } else if (roll < 0.85) {
                this.world.say(token, PHRASES[Math.floor(this.random() * PHRASES.length)]!.id, now)
            } else {
                this.world.emote(token, EMOTES[Math.floor(this.random() * (EMOTES.length - 1))]!.id, now)
            }
        }
    }
}
