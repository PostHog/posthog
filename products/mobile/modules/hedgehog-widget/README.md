# Hedgehog widget

A home-screen widget for iOS and Android with a PostHog hedgehog that wanders, jumps, waves and dances.
Eight illustrated hoggies visit for coffee breaks, parties, magic, adventures, naps, flights, reading and floating.
Tapping the hog reveals a surprise visitor, then returns to the scheduled routine.
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
     The hedgehog is an interactive `Button(intent:)` that moves with the sprite: a tap on it plays a reaction right away.
     A tap anywhere else opens the app.
   - **Android (RemoteViews)** supports `ViewFlipper` with `autoStart`, which is real frame animation inside a widget.
     It uses the script's *loops*: a closed cycle of ticks (pose frame + position) that it flips through every `tickMs`.
     The provider picks the loop for the current ten-minute slot, so the routine changes over the day.
     Each frame's sprite sends the poke broadcast, and a tap anywhere else opens the app.
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
    bubble?: string // at most 24 characters; iOS speech bubbles only on ticks with y 0, Android captions use the first loop tick
    turn?: number // iOS only: turns added on the way into this tick, clockwise on screen. A flip is two ticks of 0.5 each (up, then down).
    hoggie?: 'coffee_cup' | 'party' | 'wizard' | 'explorer' | 'asleep' | 'superhero' | 'reading' | 'float'
    // A bundled illustration replaces the pixel sprite. Missing/unknown artwork falls back to the pixel sprite.
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
    surprises?: { keyframes: Tick[]; ticks: Tick[] }[] // newer scripts offer illustrated tap reactions; old scripts still use reaction
    // Reaction ticks are authored at x 0.5 facing right. A renderer shifts every x by (current x - 0.5), clamps, and keeps the current facing, so the hedgehog reacts where it stands.
    // When the current facing is left, the renderer also negates `turn`, so a flip still goes forwards.
}
```

Illustrations and surprises are additive version 1 fields, so an older native widget can still play a newer script.
Both platforms select a surprise using the tap's epoch milliseconds modulo the surprise count.
The selection stays the same across reloads for that tap. No network request or extra refresh alarm is needed.
iOS interleaves visitor scenes with roaming; Android alternates roaming and visitor loops every ten minutes.
Each Android loop holds one character for the whole cycle and closes in the same position and facing.
Android shows visitor dialogue in a caption above the animation; iOS places it above the hog.

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

### Illustrated visitors

The illustrations come from [PostHog's hoggies library](https://brand.posthog.com/hoggies):
`coffee-cup.png`, `party.png`, `wizard-1.png`, `explorer.png`, `asleep.png`, `superhero.png`, `reading.png` and `float.png`.
Download them from `https://brand.posthog.com/hoggies/<filename>` into a local directory and name `wizard-1.png` as `wizard.png`.
Run `scripts/prepare_widget_hoggies.py --source <directory>` with Pillow available to regenerate both platforms' assets.
It trims transparent margins, normalizes facing, and fits each illustration into a 320px transparent cell with its bottom at 312px.
Artwork fits within x 40..280 and y 40..312; SwiftUI uses those bounds when clamping visitors inside the widget.
Android also bundles mirrored `_l` copies. The widget never downloads artwork at runtime.

## Identifiers

| | iOS | Android |
| --- | --- | --- |
| Widget | kind `HedgehogWidget`, target `HedgehogWidget`, bundle id `com.posthog.code.mobile.HedgehogWidget` | receiver `HedgehogWidgetProvider` |
| App Group | `group.com.posthog.code.mobile` | n/a |
| Tap on the hedgehog | `PokeHedgehogIntent` (AppIntent) | broadcast `com.posthog.code.mobile.HEDGEHOG_POKE` |
| Tap anywhere else | opens the app (default widget tap) | launch intent on `hedgehog_root` |
