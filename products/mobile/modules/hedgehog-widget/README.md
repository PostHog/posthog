# Hedgehog widget

A home-screen widget for iOS and Android with a PostHog hedgehog that wanders, jumps, waves and dances.
The app has no hedgehog mode of its own yet; the widget is the only place the hedgehog appears.

## How it moves

Widgets cannot run JavaScript and cannot animate at frame rate on their own.
So the app's JavaScript plans the choreography and the widget plays it back:

1. `src/features/hedgehog/choreography.ts` generates a deterministic, seeded script for the day
   (where the hedgehog stands, which pose it holds, where it goes next).
2. `useHedgehogWidgetSync` hands the script to this native module on launch and when the app returns to the foreground.
   The module writes it to shared storage the widget can read (an App Group on iOS, SharedPreferences on Android) and asks the OS to refresh the widget.
3. Each platform plays the script with what the OS allows:
   - **iOS (WidgetKit)** cannot animate continuously, so it uses the script's *keyframes*, one per 2-second beat.
     From iOS 17 WidgetKit animates the change between entries, so the hedgehog glides, hops, flips and turns to its next spot.
     Each move has its own animation: travel lasts until the next beat, a jump rises slowly and falls fast, and a flip turns with the jump.
     WidgetKit reportedly shows entries no faster than about every 2 seconds and stops updating a timeline of more than about 400 entries, so a timeline holds about 10 minutes of beats (identical keyframes merge into one entry).
     After them comes one entry a minute for 40 minutes, so the hedgehog keeps moving if the system delays the next reload to save its daily budget.
     The whole widget is an interactive `Button(intent:)`: a tap anywhere plays a reaction right away. The widget never opens the app; the app has no hedgehog surface to open.
   - **Android (RemoteViews)** supports `ViewFlipper` with `autoStart`, which is real frame animation inside a widget.
     It uses the script's *loops*: a closed cycle of ticks (pose frame + position) that it flips through every `tickMs`.
     The provider picks the loop for the current ten-minute slot, so the routine changes over the day.
4. With no script in shared storage (the app was never opened) each platform plays a small built-in fallback.

## Choreography JSON (version 1)

```ts
type Pose = 'idle' | 'walk' | 'jump' | 'wave' | 'action' | 'fall'
type Facing = 'left' | 'right'

interface Tick {
    pose: Pose
    frame: number // index into the pose's sprite frames, see "Sprites"
    x: number // 0..1, centre of the hedgehog across the widget width (0 = left edge, 1 = right edge; renderers clamp so it stays inside)
    y: number // 0..1, height above the floor: 0 = feet on the floor, 1 = top of the widget
    facing: Facing
    bubble?: string // optional speech bubble, at most 24 characters, iOS keyframes only. Only on ticks with y 0
    turn?: number // iOS only: turns added on the way into this tick, clockwise on screen. A flip is two ticks of 0.5 each (up, then down).
    // Consecutive ticks with a turn add up, and the run ends on whole turns with y 0, so the hedgehog lands upright
}

interface Choreography {
    version: 1
    seed: number
    generatedAt: string // ISO 8601 UTC
    startsAt: string // ISO 8601 UTC; keyframes[0] is shown from here
    keyframeSec: 2 // iOS: one keyframe every keyframeSec seconds
    keyframes: Tick[] // 900 (30 minutes). A renderer that runs past the end wraps around (index modulo length), and the last keyframe leads back to the first
    tickMs: 120 // Android: one tick every tickMs milliseconds
    loopMinutes: 10 // Android: loop index = floor(minutesSince(startsAt) / loopMinutes) modulo loops.length
    loops: Tick[][] // each loop is a closed cycle (last tick ends near the first) of at most 120 ticks
    reaction: { keyframes: Tick[]; ticks: Tick[] } // played after a tap: iOS inserts the keyframes right away (one every 2 seconds), Android plays the ticks once.
    // Reaction ticks are authored at x 0.5 facing right. A renderer shifts every x by (current x - 0.5), clamps, and keeps the current facing, so the hedgehog reacts where it stands.
    // When the current facing is left, the renderer also negates `turn`, so a flip still goes forwards.
}
```

Shared storage:

| Platform | Store | Keys |
| --- | --- | --- |
| iOS | `UserDefaults(suiteName: "group.com.posthog.code.mobile")` | `choreography` (JSON string); per widget family (`systemSmall`, `systemMedium`): `pokedAt.<family>` (seconds since 1970, Double), `reactionPoke.<family>` and `reactionStart.<family>` (written by the widget once it has scheduled the reaction for that poke, so a later reload does not replay it) |
| Android | `SharedPreferences` file `hedgehog_widget` | `choreography` (JSON string), `pokedAt` (Long, epoch ms) |

## Native module API (`modules/hedgehog-widget`)

```ts
import { isAvailable, setChoreography, clearChoreography } from 'hedgehog-widget'

isAvailable(): boolean // false on web and when the native module is missing
setChoreography(json: string): void // persist the script and refresh every placed widget
clearChoreography(): void // remove the script; widgets fall back to the built-in routine
```

## Sprites

Frames come from `@posthog/hedgehog-mode`'s TexturePacker atlas (`assets/sprites.json` + `assets/sprites.png`), default skin only.
`scripts/extract_hedgehog_sprites.py` cuts each 80x80 frame out, upscales it 2x with nearest-neighbour (pixel art stays crisp), and writes:

- Android: `modules/hedgehog-widget/android/src/main/res/drawable-nodpi/hog_<pose>_<NN>.png`, plus a mirrored `hog_<pose>_<NN>_l.png` for `facing: 'left'` (RemoteViews cannot flip an ImageView)
- iOS: `targets/HedgehogWidget/Assets.xcassets/hog_<pose>_<NN>.imageset/` (with `Contents.json`)

`<NN>` is the zero-padded frame index. Frame counts: idle 25, walk 11, jump 10, wave 26, action 16, fall 9.
Every atlas frame faces right. iOS mirrors with `scaleEffect(x: -1)`; Android uses the `_l` resources.
The sprite's feet sit about 4px above the bottom of the 160px cell (opaque body x 28..130, y 36..156 in `hog_idle_00`), so put the cell's bottom edge on the floor line. Jump and fall frames do not move inside the cell; height comes only from `y`.

## Identifiers

| | iOS | Android |
| --- | --- | --- |
| Widget | kind `HedgehogWidget`, target `HedgehogWidget`, bundle id `com.posthog.code.mobile.HedgehogWidget` | receiver `HedgehogWidgetProvider` |
| App Group | `group.com.posthog.code.mobile` | n/a |
| Tap anywhere on the widget | `PokeHedgehogIntent` (AppIntent) | broadcast `com.posthog.code.mobile.HEDGEHOG_POKE` |
