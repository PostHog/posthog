import { ComponentType } from 'react'

import { colors } from '@posthog/brand/colors'
import * as coffeeRunPng from '@posthog/brand/hoggies/png/coffee-run'
import * as coolCarPng from '@posthog/brand/hoggies/png/cool-car'
import * as experimentPng from '@posthog/brand/hoggies/png/experiment'
import * as finalEvolutionPng from '@posthog/brand/hoggies/png/final-evolution'
import * as marathonPng from '@posthog/brand/hoggies/png/marathon'
import * as mixmasterPng from '@posthog/brand/hoggies/png/mixmaster'
import * as partyPng from '@posthog/brand/hoggies/png/party'
import * as phoneCallPng from '@posthog/brand/hoggies/png/phone-call'
import * as puzzlePng from '@posthog/brand/hoggies/png/puzzle'
import * as robotPng from '@posthog/brand/hoggies/png/robot'
import * as rocketPng from '@posthog/brand/hoggies/png/rocket'
import * as selfiePng from '@posthog/brand/hoggies/png/selfie'
import * as sleepyPng from '@posthog/brand/hoggies/png/sleepy'
import * as starPng from '@posthog/brand/hoggies/png/star'
import * as superheroPng from '@posthog/brand/hoggies/png/superhero'
import * as surferPng from '@posthog/brand/hoggies/png/surfer'
import * as wizardPng from '@posthog/brand/hoggies/png/wizard-1'

import { HoggiePngProps, pngHoggie } from 'lib/brand/hoggies'

import type { ArchetypeEnumApi } from '../generated/api.schemas'
import type { WrappedCardKey } from './storyCards'

type Hoggie = ComponentType<HoggiePngProps>

export interface WrappedCardTheme {
    background: string
    // Light grounds take dark text; every other card is white on a dark or saturated ground.
    light: boolean
    hoggie: Hoggie
}

// The story paints its own grounds from the brand palette, the same in light and dark mode, like a poster.
const deep = (color: string): string => `color-mix(in srgb, ${color} 22%, black)`
const glow = (color: string, at: string, size = '100% 70%'): string =>
    `radial-gradient(${size} at ${at}, color-mix(in srgb, ${color} 85%, transparent) 0%, transparent 62%)`
const fade = (...stops: string[]): string => `linear-gradient(165deg, ${stops.join(', ')})`

const hoggies = {
    party: pngHoggie(partyPng),
    rocket: pngHoggie(rocketPng),
    star: pngHoggie(starPng),
    phoneCall: pngHoggie(phoneCallPng),
    robot: pngHoggie(robotPng),
    experiment: pngHoggie(experimentPng),
    coffeeRun: pngHoggie(coffeeRunPng),
    sleepy: pngHoggie(sleepyPng),
    superhero: pngHoggie(superheroPng),
    marathon: pngHoggie(marathonPng),
    wizard: pngHoggie(wizardPng),
    mixmaster: pngHoggie(mixmasterPng),
    surfer: pngHoggie(surferPng),
    coolCar: pngHoggie(coolCarPng),
    finalEvolution: pngHoggie(finalEvolutionPng),
    puzzle: pngHoggie(puzzlePng),
    selfie: pngHoggie(selfiePng),
}

export const CARD_THEMES: Record<WrappedCardKey, WrappedCardTheme> = {
    intro: {
        background: `${glow(colors.violet.core, '90% 5%')}, ${glow(colors.tangerine.core, '0% 100%')}, ${deep(colors.violet.darker)}`,
        light: false,
        hoggie: hoggies.party,
    },
    tool_calls: {
        background: `${glow(colors.lemon.core, '100% 0%', '90% 60%')}, ${fade(colors.tangerine.core, colors.tangerine.darker, colors.coral.darker)}`,
        light: false,
        hoggie: hoggies.rocket,
    },
    top_tools: {
        background: `${glow(colors.violet.core, '100% 0%')}, ${fade(colors.cobalt.core, colors.cobalt.darker)}`,
        light: false,
        hoggie: hoggies.star,
    },
    apps: {
        background: `${glow(colors['corn-blue'].core, '0% 0%', '90% 60%')}, ${fade(colors.violet.core, colors.violet.darker)}`,
        light: false,
        hoggie: hoggies.phoneCall,
    },
    labs: {
        background: `${glow(colors['corn-blue'].core, '95% 0%')}, ${glow(colors.teal.core, '0% 100%', '90% 60%')}, ${deep(colors.cobalt.darker)}`,
        light: false,
        hoggie: hoggies.robot,
    },
    models: {
        background: `${glow(colors.coral.lighter, '0% 0%')}, ${fade(colors.purple.core, colors.purple.darker)}`,
        light: false,
        hoggie: hoggies.experiment,
    },
    rush_hour: {
        background: `${glow(colors.tangerine.core, '100% 100%', '90% 60%')}, ${fade(colors.lemon.lighter, colors.lemon.core, colors.yellow.core)}`,
        light: true,
        hoggie: hoggies.coffeeRun,
    },
    reliability: {
        background: `${glow(colors.teal.lighter, '100% 0%', '90% 60%')}, ${fade(colors.teal.core, colors.teal.darker)}`,
        light: true,
        hoggie: hoggies.superhero,
    },
    speed: {
        background: `${glow(colors.cobalt.core, '100% 100%', '90% 60%')}, ${glow(colors.teal.core, '0% 0%', '70% 50%')}, ${deep(colors.cobalt.darker)}`,
        light: false,
        hoggie: hoggies.marathon,
    },
    archetype: {
        background: `${glow(colors.tangerine.core, '85% 15%', '85% 60%')}, ${glow(colors.purple.core, '5% 95%')}, ${deep(colors.violet.core)}`,
        light: false,
        hoggie: hoggies.wizard,
    },
    share: {
        background: `${glow(colors.lemon.core, '100% 0%', '90% 60%')}, ${fade(colors.tangerine.core, colors.coral.core, colors.purple.core)}`,
        light: false,
        hoggie: hoggies.selfie,
    },
}

export const ARCHETYPE_HOGGIES: Record<ArchetypeEnumApi, Hoggie> = {
    one_hit_wonder: hoggies.mixmaster,
    swiss_army_knife: hoggies.wizard,
    night_owl: hoggies.sleepy,
    weekend_warrior: hoggies.surfer,
    speed_demon: hoggies.coolCar,
    rocket: hoggies.finalEvolution,
    superhero: hoggies.superhero,
    all_rounder: hoggies.puzzle,
}

export const NIGHT_SHIFT_HOGGIE = hoggies.sleepy
