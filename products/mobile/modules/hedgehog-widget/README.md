# Hedgehog widget

A home-screen widget for iOS and Android with a PostHog hedgehog that wanders, jumps, waves and dances.
Tapping the hog cycles through eight illustrated characters: coffee, party, wizard, explorer, asleep, superhero, reading and float.
The selected character stays until the next tap, including across app launches and daily script syncs.
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
     Walking interpolates continuously between destinations across the full two-second interval. A geometry group keeps
     the button’s content updates from overriding its position animation; facing changes do not insert a stationary beat.
     Hops and flips use built-in rotations that complete a full turn within the same interval. Every entry ends upright on the ground,
     so a delayed or skipped update cannot leave the hog upside down. Image changes and facing changes do not crossfade or spring.
     The widget saves its scheduled entries per family: tapping changes only the character, and a refresh resumes the
     existing timeline. After it expires, the new routine starts at the last position instead of a distant wall-clock sample.
     Dialogue is not rendered on either platform, including when reading an older script.
     The hedgehog is an interactive `Button(intent:)`; a tap anywhere else opens the app.
   - **Android (RemoteViews)** uses `ViewFlipper` to play a closed loop, interpolating four positions every 30 ms (about 33 fps) for the standard 120 ms script.
     A placed widget keeps its loop across daily script syncs. Android 12+ reuses stable frame views so taps, refreshes
     and resizing retain the launcher's displayed frame. On older Android versions, a tap carries the visible frame's
     index and restores it when the views are rebuilt; an OS recreation or resize may restart the loop.
     There are no periodic loop replacements or reaction-end alarms. Each frame's sprite sends its own poke broadcast,
     scoped to that widget, and a tap anywhere else opens the app.
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
    bubble?: string // legacy dialogue; ignored by the native renderers
    turn?: number // legacy half-turn markers; iOS plays one complete flip when entering an airborne sequence
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
    reaction: { keyframes: Tick[]; ticks: Tick[] } // legacy tap reaction, retained for compatibility with older native builds.
    surprises?: { keyframes: Tick[]; ticks: Tick[] }[] // legacy illustrated reactions, retained for older native builds
    // Reaction ticks are authored at x 0.5 facing right. A renderer shifts every x by (current x - 0.5), clamps, and keeps the current facing, so the hedgehog reacts where it stands.
}
```

Illustrations and surprises remain in version 1 for older native builds. Current widgets ignore scripted character
changes and apply their saved selection to every movement frame. Every tap advances to a different bundled character.
New scripts contain no automatic visitor scenes. The first character is the pixel hedgehog until the first tap.

Shared storage:

| Platform | Store | Keys |
| --- | --- | --- |
| iOS | `UserDefaults(suiteName: "group.com.posthog.code.mobile")` | `choreography` (JSON string); per family: `selectedHog.<family>` and `timeline.v2.<family>` (encoded scheduled entries) |
| Android | `SharedPreferences` file `hedgehog_widget` | `choreography` (JSON string); per widget ID: `selectedHog.<id>` and `loop.<id>` (saved movement loop) |

## Garden background

Both widgets bundle the grass layer from PostHog's **Keyboard Garden** website wallpaper, used by
[`src/components/Desktop/Wallpapers.tsx`](https://github.com/PostHog/posthog.com/blob/master/src/components/Desktop/Wallpapers.tsx).
The source is [`9000_bg_light_07316896be.jpg`](https://res.cloudinary.com/dmukukwp6/image/upload/9000_bg_light_07316896be.jpg),
downloaded at 1000px wide (`/image/upload/w_1000/9000_bg_light_07316896be.jpg`).
It is bundled as `hoglet_garden.jpg` in both native asset catalogs and fills the widget with a centered crop.
There is no runtime image download.

## Native timeline check

From `products/mobile` on macOS:

```sh
swiftc targets/HedgehogWidget/{Choreography,HedgehogTimelineProvider}.swift scripts/check_hedgehog_timeline.swift -o /tmp/check-hoglet
/tmp/check-hoglet
```

This checks tap and reload continuity, character cycling, timeline persistence and delayed refreshes.

## Native module API (`modules/hedgehog-widget`)

```ts
import { isAvailable, setChoreography, clearChoreography } from 'hedgehog-widget'

isAvailable(): boolean // false on web and when the native module is missing
setChoreography(json: string): void // persist the script and refresh every placed widget
clearChoreography(): void // remove the source script; new routines use the fallback, placed widgets retain their current motion
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
