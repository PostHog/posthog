import { ComponentType } from 'react'

import { colors } from '@posthog/brand/colors'
import * as campfirePng from '@posthog/brand/hoggies/png/campfire-cowboy'
import * as coffeeCupPng from '@posthog/brand/hoggies/png/coffee-cup'
import * as constructionPng from '@posthog/brand/hoggies/png/construction-1'
import * as coolCarPng from '@posthog/brand/hoggies/png/cool-car'
import * as djPng from '@posthog/brand/hoggies/png/dj'
import * as doctorPng from '@posthog/brand/hoggies/png/doctor-1'
import * as evelPng from '@posthog/brand/hoggies/png/evel'
import * as gladiatorPng from '@posthog/brand/hoggies/png/gladiator-2'
import * as hootPng from '@posthog/brand/hoggies/png/hoot'
import * as hourglassPng from '@posthog/brand/hoggies/png/hourglass'
import * as ipadPng from '@posthog/brand/hoggies/png/ipad'
import * as maestroPng from '@posthog/brand/hoggies/png/maestro'
import * as marathonPng from '@posthog/brand/hoggies/png/marathon'
import * as panicPng from '@posthog/brand/hoggies/png/panic'
import * as partyPng from '@posthog/brand/hoggies/png/party'
import * as phoneCallPng from '@posthog/brand/hoggies/png/phone-call'
import * as robotPng from '@posthog/brand/hoggies/png/robot'
import * as rocketPng from '@posthog/brand/hoggies/png/rocket'
import * as scientistPng from '@posthog/brand/hoggies/png/scientist'
import * as sleepyPng from '@posthog/brand/hoggies/png/sleepy'
import * as starPng from '@posthog/brand/hoggies/png/star'
import * as superheroPng from '@posthog/brand/hoggies/png/superhero'
import * as transformerPng from '@posthog/brand/hoggies/png/transformer'
import * as workmaxxingPng from '@posthog/brand/hoggies/png/workmaxxing'

import { HoggiePngProps, pngHoggie } from 'lib/brand/hoggies'

import type { ArchetypeEnumApi } from '../generated/api.schemas'
import type { DayPart, ReliabilityTier, SpeedTier, WrappedCardKey } from './storyCards'

type Hoggie = ComponentType<HoggiePngProps>

export interface WrappedCardTheme {
    background: string
    hoggie: Hoggie
}

// The story paints its own grounds from the brand palette, the same in light and dark mode, like a poster.
const deep = (color: string): string => `color-mix(in srgb, ${color} 22%, black)`
const glow = (color: string, at: string, size = '100% 70%'): string =>
    `radial-gradient(${size} at ${at}, color-mix(in srgb, ${color} 85%, transparent) 0%, transparent 62%)`
const fade = (...stops: string[]): string => `linear-gradient(165deg, ${stops.join(', ')})`

// PostHog's dark app ground (--color-bg-3000-dark). The brand palette has no neutral, and the share card sits
// between dark story cards.
const POSTHOG_DARK = '#1D1F27'
// Many brand colors are too light under white text at full strength. A share of the dark ground keeps the hue
// and brings white text to 4.5:1 or better.
const rich = (color: string, share: number): string => `color-mix(in srgb, ${color} ${share}%, ${POSTHOG_DARK})`
const soft = (color: string, at: string, size: string): string =>
    `radial-gradient(${size} at ${at}, color-mix(in srgb, ${color} 45%, transparent) 0%, transparent 70%)`
// A card's ground: one color fading down the card, and a related glow low in the corner behind the hedgehog,
// away from the text.
const ground = (glowColor: string, from: string, to: string): string =>
    `${glow(glowColor, '100% 100%', '90% 55%')}, ${fade(from, to)}`

const hoggies = {
    party: pngHoggie(partyPng),
    phoneCall: pngHoggie(phoneCallPng),
    dj: pngHoggie(djPng),
    ipad: pngHoggie(ipadPng),
    scientist: pngHoggie(scientistPng),
    robot: pngHoggie(robotPng),
    coffeeCup: pngHoggie(coffeeCupPng),
    workmaxxing: pngHoggie(workmaxxingPng),
    campfire: pngHoggie(campfirePng),
    sleepy: pngHoggie(sleepyPng),
    doctor: pngHoggie(doctorPng),
    construction: pngHoggie(constructionPng),
    panic: pngHoggie(panicPng),
    marathon: pngHoggie(marathonPng),
    coolCar: pngHoggie(coolCarPng),
    hourglass: pngHoggie(hourglassPng),
    star: pngHoggie(starPng),
    transformer: pngHoggie(transformerPng),
    hoot: pngHoggie(hootPng),
    gladiator: pngHoggie(gladiatorPng),
    evel: pngHoggie(evelPng),
    rocket: pngHoggie(rocketPng),
    superhero: pngHoggie(superheroPng),
    maestro: pngHoggie(maestroPng),
}

// These hedgehogs' art runs to the edge of the image, so the card's edge would cut them off in the corner.
const EDGE_TO_EDGE_HOGGIES: ReadonlySet<Hoggie> = new Set([
    hoggies.campfire,
    hoggies.sleepy,
    hoggies.construction,
    hoggies.marathon,
    hoggies.coolCar,
])

export function hoggieReachesEdge(hoggie: Hoggie): boolean {
    return EDGE_TO_EDGE_HOGGIES.has(hoggie)
}

// Every card takes its color from what it shows. A card with one subject takes its hedgehog's colors, and a card
// whose data has a mood (time of day, error rate, response time, personality) takes the mood of the data, so the
// same card reads differently for different servers. Every ground keeps white text at 4.5:1 or better.

/** The sky at the busiest hour: sunrise, daylight, sunset or night. */
export const RUSH_HOUR_THEMES: Record<DayPart, WrappedCardTheme> = {
    morning: {
        background: ground(colors.lemon.core, rich(colors.yellow.core, 55), rich(colors.tangerine.darker, 60)),
        hoggie: hoggies.coffeeCup,
    },
    day: {
        background: ground(colors.lemon.lighter, rich(colors.blue.core, 80), rich(colors.blue.darker, 75)),
        hoggie: hoggies.workmaxxing,
    },
    evening: {
        background: `${glow(colors.yellow.core, '100% 100%', '70% 45%')}, ${glow(colors.tangerine.core, '50% 100%', '120% 55%')}, ${fade(rich(colors.purple.darker, 82), rich(colors.violet.darker, 60))}`,
        hoggie: hoggies.campfire,
    },
    night: {
        background: `${glow(colors.violet.core, '100% 100%', '90% 55%')}, ${deep(colors.violet.darker)}`,
        // The agents worked the night shift while you slept. Not the owl, which the Night Owl personality shows.
        hoggie: hoggies.sleepy,
    },
}

/** Green for a healthy year, amber for a bumpy one, red for a rough one. */
export const RELIABILITY_THEMES: Record<ReliabilityTier, WrappedCardTheme> = {
    healthy: {
        background: ground(colors.green.core, rich(colors.green.darker, 70), rich(colors.green.darker, 55)),
        // A clean bill of health. Not the superhero: the Superhero personality needs a healthy year, so it
        // would show the same hedgehog twice.
        hoggie: hoggies.doctor,
    },
    bumpy: {
        background: ground(colors.yellow.core, rich(colors.yellow.core, 55), rich(colors.yellow.darker, 50)),
        hoggie: hoggies.construction,
    },
    rough: {
        background: ground(colors.tangerine.core, rich(colors.coral.core, 80), rich(colors.coral.darker, 66)),
        hoggie: hoggies.panic,
    },
}

/** Electric blue for quick answers, sky blue for steady ones, orange for slow ones. */
export const SPEED_THEMES: Record<SpeedTier, WrappedCardTheme> = {
    fast: {
        background: ground(colors['corn-blue'].core, colors.cobalt.core, colors.cobalt.darker),
        hoggie: hoggies.marathon,
    },
    steady: {
        background: ground(colors['corn-blue'].core, rich(colors.blue.core, 80), rich(colors.blue.darker, 75)),
        hoggie: hoggies.coolCar,
    },
    // Orange, not the bumpy reliability amber, so a slow and bumpy year doesn't show the same card twice.
    slow: {
        background: ground(colors.yellow.core, rich(colors.tangerine.core, 76), rich(colors.tangerine.darker, 62)),
        hoggie: hoggies.hourglass,
    },
}

export const ARCHETYPE_HOGGIES: Record<ArchetypeEnumApi, Hoggie> = {
    one_hit_wonder: hoggies.star,
    // One machine that turns into whatever the job needs.
    swiss_army_knife: hoggies.transformer,
    night_owl: hoggies.hoot,
    weekend_warrior: hoggies.gladiator,
    speed_demon: hoggies.evel,
    rocket: hoggies.rocket,
    superhero: hoggies.superhero,
    all_rounder: hoggies.maestro,
}

// Each personality's color comes from its hedgehog or sets it off: the star's gold, the superhero's cape, the
// night sky the red rocket climbs into, the sea green behind the gladiator's bronze.
const ARCHETYPE_COLORS: Record<ArchetypeEnumApi, string> = {
    one_hit_wonder: colors.yellow.core,
    swiss_army_knife: colors.cobalt.core,
    night_owl: colors.blue.core,
    weekend_warrior: colors.teal.core,
    speed_demon: colors.tangerine.core,
    rocket: colors.violet.core,
    superhero: colors.coral.core,
    all_rounder: colors.purple.core,
}

/** The personality reveal: a dark ground in the personality's color, glowing behind its hedgehog. */
export function archetypeTheme(archetype: ArchetypeEnumApi): WrappedCardTheme {
    const color = ARCHETYPE_COLORS[archetype]
    return {
        background: `${glow(color, '50% 85%', '100% 55%')}, ${deep(color)}`,
        hoggie: ARCHETYPE_HOGGIES[archetype],
    }
}

/** The poster: PostHog's dark ground, lit in the corner by the personality's color, with its hedgehog. */
export function shareTheme(archetype: ArchetypeEnumApi): WrappedCardTheme {
    return {
        background: `${soft(ARCHETYPE_COLORS[archetype], '95% 5%', '60% 35%')}, ${soft(colors.yellow.core, '50% 38%', '70% 30%')}, ${soft(colors.violet.core, '0% 100%', '70% 40%')}, ${POSTHOG_DARK}`,
        hoggie: ARCHETYPE_HOGGIES[archetype],
    }
}

/** The theme for each card when it has no data of its own to pick one, and for the cards with one subject. */
export const CARD_THEMES: Record<WrappedCardKey, WrappedCardTheme> = {
    intro: {
        background: `${glow(colors.violet.core, '90% 5%')}, ${glow(colors.tangerine.core, '0% 100%')}, ${deep(colors.violet.darker)}`,
        hoggie: hoggies.party,
    },
    // A calm sea teal between the violet intro and the cobalt top tool card.
    tool_calls: {
        background: ground(colors.teal.lighter, rich(colors.teal.darker, 58), rich(colors.teal.darker, 40)),
        hoggie: hoggies.phoneCall,
    },
    // The most-called tool is the year's top track, so the DJ plays it, in the blue of its hoodie under club lights.
    top_tools: {
        background: ground(colors.purple.core, colors.cobalt.core, colors.cobalt.darker),
        hoggie: hoggies.dj,
    },
    apps: {
        background: ground(colors['corn-blue'].core, colors.violet.core, colors.violet.darker),
        hoggie: hoggies.ipad,
    },
    // The pink of the flask on the scientist's bench.
    labs: {
        background: ground(colors.coral.lighter, colors.purple.core, colors.purple.darker),
        hoggie: hoggies.scientist,
    },
    // The robot's steel, with its lights glowing teal.
    models: {
        background: ground(colors.teal.core, rich(colors['corn-blue'].darker, 90), rich(colors.blue.darker, 70)),
        hoggie: hoggies.robot,
    },
    rush_hour: RUSH_HOUR_THEMES.evening,
    reliability: RELIABILITY_THEMES.healthy,
    speed: SPEED_THEMES.fast,
    archetype: archetypeTheme('all_rounder'),
    share: shareTheme('all_rounder'),
}
