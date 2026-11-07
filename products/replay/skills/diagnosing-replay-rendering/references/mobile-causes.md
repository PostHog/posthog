# Mobile rendering causes

Mobile SDKs do not record a DOM.
They record either a **wireframe** (a description of the view tree) or a **screenshot** of the screen, and the player converts both to HTML.
In the export you see the converted HTML:

- Screenshot mode: an `<img data-posthog-screenshot="true">` whose `src` is a PNG of the whole screen.
- Wireframe mode: absolutely positioned `<div>`, text, `<img>` and input nodes.
- Something the SDK could not draw: a `<div>` with a placeholder background image and a text label such as `web_view`, `placeholder`, or a web view's URL.

| SDK          | Modes                                                                              |
| ------------ | ---------------------------------------------------------------------------------- |
| Android      | Wireframe by default. Screenshot with `sessionReplayConfig.screenshot = true`.     |
| iOS          | Wireframe by default. Screenshot with `sessionReplayConfig.screenshotMode = true`. |
| React Native | Always screenshot. Do not suggest wireframe or screenshot settings.                |
| Flutter      | Always screenshot.                                                                 |

Masking is on by default, and masks are painted as solid blocks.
A black block in a screenshot is almost always a mask, not missing data.
Mobile SDKs do not write `$session_options` or `$posthog_config`, so the SDK config is not in the recording.
Get the SDK and version with SQL (`$lib`, `$lib_version`) and ask the user for their `sessionReplayConfig` when a cause depends on it.

Docs: https://posthog.com/docs/session-replay/mobile and https://posthog.com/docs/session-replay/privacy

## Map, web view, or camera is a black block

**Symptom:** a big black rectangle where a map, web view, video, or camera preview should be. The rest of the screen is fine.

| SDK          | Cause                                                                                                                                    | Fix                                                                                                                                                                     |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Flutter      | `sessionReplayConfig.maskAllPlatformViews` is `true` by default and paints every platform view black.                                    | Set it to `false`, or wrap one view in `PostHogPlatformView` with `PostHogPlatformViewPrivacy.capture`.                                                                 |
| Flutter      | The mask spills past the map onto widgets below it.                                                                                      | Fixed in posthog_flutter 5.38.1. Upgrade.                                                                                                                               |
| React Native | With `maskAllImages` or `maskAllTextInputs` on (both default `true`), the SDK masks a whole web view, because it cannot mask inside one. | Add `accessibilityLabel="ph-no-mask"` to a wrapping `View`. It unmasks the whole subtree, so do not put it around forms.                                                |
| Android, iOS | Image and text masking defaults.                                                                                                         | Set `maskAllImages` / `maskAllTextInputs` to `false` and mask sensitive views on purpose (`ph-no-capture` tag, `.postHogMask()`), or unmask one view with `ph-no-mask`. |

Limits:

- Flutter on iOS can only reveal platform views backed by a web view. Maps and camera stay masked.
- Flutter Google Maps is always masked.
- Masks are drawn flat with no z-order, so a sheet drawn over a masked area also looks black.

**Evidence:** decode the screenshot near the symptom time and look for a solid black rectangle.
The Meta `href` is the screen or route name, which often names the screen with the map or web view.

## Grey boxes, no text, no images

**Symptom:** "all recordings are blank grey screens", or a logo and nothing else.

**Evidence:** no `data-posthog-screenshot` image, and the nodes are mostly empty `<div>` boxes with few text nodes and no images (`text_nodes` and `images` near zero in the inventory).

**Cause:** wireframe mode reads the classic Android View and UIKit trees. Jetpack Compose and SwiftUI content does not map well to it.

**Fix:** turn on screenshot mode: `sessionReplayConfig.screenshot = true` on Android, `sessionReplayConfig.screenshotMode = true` on iOS. Review masking first, because screenshots capture everything on the screen.

## One frame that never changes

**Symptom:** every replay shows the same view and does not play, or the screen is blank while touches move.

**Evidence:** touch events (source 2) for minutes, and no full snapshot (type 2) and no screenshots after the first frame, or none at all.

| SDK     | Cause and fix                                                                                                                                                                                          |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Flutter | `PostHogWidget` mounted before `Posthog().setup()` finished, so touches record but screens do not. Call `WidgetsFlutterBinding.ensureInitialized(); await Posthog().setup(config);` before `runApp()`. |
| Any     | The first screen never reached PostHog (app closed, offline). No fix for that recording.                                                                                                               |

## Flutter web shows a white page

**Symptom:** a Flutter web app replays as an empty white page.

**Evidence:** canvas frames (source 9) whose `data.id` is not a node in any full snapshot or mutation add. CanvasKit added its `<canvas>` inside the `flt-glass-pane` shadow root after the full snapshot.

**Fix:** turn on canvas capture. After the Flutter canvas exists, restart recording (`posthog.stopSessionRecording()` then `posthog.startSessionRecording()`) to force a new full snapshot.

## Black or white screens with no clear cause

Android white screens, iOS SwiftUI black screens, and a full-screen Rive animation that turns the screen black are open questions in support.
Collect what an engineer needs and say the cause is not known:

- SDK and version. Recommend the current SDK first; many dropped-frame fixes shipped in recent Android and iOS releases.
- Toolkit (Views, Compose, UIKit, SwiftUI), and the screen's Meta `href`.
- Whether screenshot mode is on.
- SDK debug logs with `debug = true`, lines that mention session replay.
- The private replay link and the player time.
