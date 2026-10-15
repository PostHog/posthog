# Design

The design handoff (README, prototype and reference screenshots) is the spec.
This file records how it maps to React Native.

## Tokens

All values live in `src/ui/tokens.ts`. Styles use `StyleSheet.create` with these values.

- `colors`: every color in the handoff, named by role (`ink`, `muted`, `secondary`, `tertiary`,
  `border`, `hairline`, `rowDivider`, `sunken`, `pressed`, `background`, `orange`, `blue`, ...),
  plus the scrims and the white overlays used on the orange button.
- `avatarPalette`, `accentColor`: keyed by the report `Accent`
  (`alert` orange, `opportunity` blue, `resolved` ink).
- `type`: the type scale. React Native letter spacing is in points, so `letterSpacing(size, em)`
  converts the handoff's em values per size. Text without an explicit line height uses the
  prototype's root line height of 1.4 (`lineHeight(size)`).
- `fonts.mono`: Menlo on iOS, `monospace` on Android, the handoff's CSS stack on web.
  Everything else uses the system font.
- `iconSizes`: 24pt for navigation and list tiles, 20pt for action buttons, search fields and
  selection marks, 16pt for inline status glyphs, 14pt for compact chip accessories, and 28pt
  for empty-state illustrations. Use the role's token at the call site instead of a glyph's default size.
- `space` (keyed by value, `space[14]`), `radii`, `layout` (gutters, 44pt tap target, and the
  prototype frame's 54pt status bar and 34pt home indicator).
- `shadows`: `shadow*` props plus Android `elevation` on native (radius is half the CSS blur);
  the exact CSS `boxShadow` on web.
- `motion`: 180ms fades, 200ms sheets and chevron, 220ms floating cards, with the handoff's
  bezier curves. `usePresence` sets every duration to 0 when reduce motion is on.
- `inputReset`, `prettyWrap`: web-only fixes, see below.

## Proportions

Body text, picker labels, menu rows and text inputs use 16pt. Sheet titles use 18pt, including
the Assignee and Project floating cards. Screen titles (28pt), report headlines (22pt),
empty-state headings (20pt), secondary text (13–15pt) and chart values keep their hierarchy.
The same action uses the same icon size across menus and report controls. List tiles and
navigation use larger glyphs; inline metadata and chip accessories use smaller ones.
The unassigned avatar occupies the same 32pt column as a person's avatar in the Assignee card.
Sizing a glyph does not change its button's tap target, which stays at least 44pt including hit slop.

## Reading handoff values

- **Box sizing.** The prototype's `div`s use CSS `content-box`, so a `height` or `min-height`
  excludes padding and border. React Native is always border-box. Where the two differ, the code
  uses the rendered size and says so in a comment: inbox rows render 71pt (44pt content), icon
  tiles 40pt, the bottom nav pill 64pt, the Chat button 56pt, the Back chip and Prev/Next pill
  46pt, the action pill 54pt, the hand-off agent row 78pt,
  @-mention rows 56pt, the mention popover 274pt max, and the nav menu 75% of the width plus 22pt.
  `button` elements in the prototype are border-box, so their sizes carry over unchanged.
- **Safe areas.** Top and bottom paddings in the handoff include the prototype's status bar
  (54pt) and home indicator (34pt). `topOffset(insets, designTop)` and
  `bottomOffset(insets, designBottom)` swap those for the device's insets. The web build has no
  insets, so `useScreenInsets` uses the prototype's values there.
- **Text wrapping.** The prototype sets `text-wrap: pretty`. iOS gets the same behavior from
  `lineBreakStrategyIOS="standard"`, and web from the CSS property (`prettyWrap`).
  Android wraps greedily.

## Component inventory

| Component | File | Notes |
| --- | --- | --- |
| `Pressable44` | `ui/Pressable44.tsx` | Default 6pt hit slop so 34pt visuals reach 44pt; pressed and hover background; optional haptic |
| `PillControl` | `ui/PillControl.tsx` | White bordered pill for icon buttons |
| `SegmentedPill` | `ui/SegmentedPill.tsx` | Equal segments with inset dividers; `raised` adds the chip shadow; `selected` state |
| `IconTile` | `ui/IconTile.tsx` | Source icon tile with the yellow needs-input badge |
| `Avatar` | `ui/Avatar.tsx` | Initials on a palette color picked from a seed |
| `MonoText`, `Eyebrow`, `Dot` | `ui/` | Mono text, uppercase label with optional dot, colored dot |
| `Scrim` | `ui/Scrim.tsx` | Fades with the overlay; optional tap to close |
| `BottomSheet` | `ui/BottomSheet.tsx` | Grabber, radius 22, slides up 200ms, closes on scrim tap or a downward drag. An optional `scrollGesture` makes a drag that starts on an inner list scroll it instead |
| `HandoffOptionRows` | `features/handoff/HandoffOptionRows.tsx` | White bordered group of 48pt rows in the hand-off sheet: muted label, right-aligned bold value with an optional tertiary second line, chevron |
| `SheetPageHeader` | `features/handoff/SheetPageHeader.tsx` | 44pt round back button and sheet title for a page that replaces the sheet's content |
| `ModelPage`, `ModePage`, `BranchPage` | `features/handoff/` | Hand-off option pages; the chat's options sheet hosts Model and Mode too, so they take the options and pick callbacks as props. Model: "Reasoning" effort pills (ink fill when picked, ink border for the default's effort when the default names one), then models under "Claude Code" and "Codex" eyebrows with the cost multiplier and a check, in a list capped at 42% of the window that scrolls without closing the sheet, and "Reset to default". Mode: label and description rows. Branch: bordered text field that lifts with the keyboard, one note and a Done button |
| `Composer` chips | `features/chat/Composer.tsx` | After `@`: a Model chip ("Default", or the pinned model without its "Claude" prefix and the effort, such as "Opus 5.5 · High") and a Mode chip ("Auto" by default). 32pt bordered pills with a chevron that reach 44pt through the hit slop, shrink and truncate to one line on a narrow phone, and dim while the agent works, the history loads, a send is in flight or a decision waits. On an open chat they start from the run's own model and mode, and the Model page lists only the run's harness |
| `ChatOptionsSheet` | `features/chat/ChatOptionsSheet.tsx` | `BottomSheet` over the chat that hosts `ModelPage` or `ModePage` for the chat's own options. The back button closes it, and a mode pick closes it. It draws inline, because the chat route is a native modal outside the overlay host |
| `FloatingCard` | `ui/FloatingCard.tsx` | Radius 28 card, scales from 0.92 and drops 6pt, 220ms emphasized curve |
| `MetricChart` | `ui/chart/MetricChart.tsx` | Line or bar chart on Skia (victory-native). The y axis floats for lines and starts at zero for bars. Hairline gridlines, 11pt mono ticks. Tap or drag to scrub, with a selection haptic and a tooltip that stays after release. 144pt high by default |
| `ObservationCard` | `features/report/metrics/ObservationCard.tsx` | White card: "Observation" eyebrow, title, caption, 28pt mono value, chart, then the window and filter count with Open insight |
| `ImpactMetrics` | `features/report/metrics/ImpactMetrics.tsx` | "Impact" eyebrow over a two-column grid of tiles: 20pt mono value, title, and the window or measured time. A tile with a link opens the insight |
| `ReportCharts` | `features/report/metrics/ReportCharts.tsx` | "Charts" eyebrow over one card per chart: title, caption, the chart when the app can draw it, and Open insight |
| `ReportContextMenu` | `features/inbox/ReportContextMenu.tsx` | Inbox row long-press menu on `FloatingCard`; nav menu width; opens 8pt below the row, or above it when the bottom bar is in the way (`contextMenuPlacement.ts`) |
| `ReportMeta` | `features/report/ReportMeta.tsx` | Byline under the headline, above the lede (source glyph and label · "Since …"), then the Owner and Priority chips: 32pt bordered pills with a chevron that open the Assignee card and the Priority sheet. No owner shows a dashed orange circle and "Assign"; P0 and P1 color their code orange |
| `Sparkline` | `ui/Sparkline.tsx` | 14 bars; height `max(2, round(v × 32 / max))`, capped at 32 (`sparklineMath.ts`) |
| `TimelineItem`, `RichText` | `ui/` | Activity entry with node, connector, `**bold**` text, via chip and time |
| `FadeEdge` | `ui/FadeEdge.tsx` | SVG gradient behind floating chrome (no gradient dependency) |
| `BlurEdge` | `ui/BlurEdge.tsx` | Masked blur of the content under floating top chrome |
| `BackChip` | `ui/BackChip.tsx` | Report and Settings back button |
| `StateView`, `LoadingView` | `ui/StateView.tsx` | Empty and error screens with a next action; loading spinner |
| `PostHogLogomark`, `PostHogLogo` | `ui/icons/PostHogLogomark.tsx`, `ui/icons/PostHogLogo.tsx` | Brand logomark and landscape lockup as SVG, sized by `height` |
| Icons | `ui/icons/*.tsx` | One component per glyph, ported from the prototype's SVG paths |

## Screens and states

- **Inbox**: header with Refresh and More, rows, pull to refresh, floating nav pill (Home selected,
  Chats, Products) and the Chat button. Chats in the pill opens the Chats screen; the Chat button
  opens a new chat sheet. Products opens the project's product library in the web app, and is
  dimmed in demo mode or when the session has no project. A long press on a row (or the screen
  reader's "Show report actions") opens a menu with Hand off to the saved agent (PostHog,
  Claude Code or Codex), Reassign, Snooze, Chat and, for an unread report, Mark as read.
  Hand off uses the same eligibility rules and saved destination as the report's hand-off button;
  it waits for report details, blocks repeat taps while pending and keeps failures in the menu for retry.
  The other actions work like the report's action pill, without leaving the inbox.
  Loading, empty and error states are separate screens.
- **Chats**: the mobile port of the web app's Chats pane. Header with the logomark, "Chats" and a
  New chat button. A search field above the list filters titles on the device. Rows are grouped
  under day labels (Today, Yesterday, a weekday, a date, Earlier) and use the inbox row geometry:
  a chat bubble tile for a PostHog AI chat, a branch tile for a report hand-off or another session,
  and an origin label, a status dot and the time under the title. A row opens the chat sheet on that
  task: the agent's thread, its PR card, and a pending decision above the composer. The nav pill
  shows Chats selected. Loading, error, empty and "No matches" are separate screens.
- **Nav menu**: project name (opens the Project card), Inbox (selected), Settings, Sign out.
- **Report**: top chrome, headline, the byline with the Owner and Priority chips (`ReportMeta`), lede,
  evidence (trace, quotes, replay), facts, the observation card, impact tiles, charts,
  activity, and the action bar.
- **Action bar** (`actionBarStateFor`): execution, attention and PR availability are independent.
  Execution distinguishes unclaimed, starting, working, idle, reconnecting, unavailable, failed,
  canceled, completed and unknown. A claim names the owner without claiming they are running.
  Only a structured pending input produces the compact Needs your answer row. Read question
  opens a bounded decision sheet with the full question, choices and a typed-answer field;
  turn completion is idle.
  A known PR stays visible during every execution state, with its draft/open/merged/closed/unknown
  state. View PR opens GitHub and View task activity opens the implementation chat. Several PRs
  use a compact selector opening the Pull requests sheet. Selected-PR checks distinguish checking,
  passing, failing, pending, no checks and unavailable, with the local fetch time. A dot beside the
  check label is green for passing, red for failing, amber for pending or unavailable, blue while
  checking, and gray when no checks are reported. The label stays visible alongside the color.
  Task status opens the
  implementation chat; the Reassign / Snooze / Chat pill starts report discussion. The pill shows
  in every state. Undo is a separate action while an answer is in flight. Transient tool text
  clears when a turn is idle or terminal and stays on one truncated line while active.
- **Overlays**: hand-off sheet, snooze sheet (with a custom time picker), Assignee card, Priority sheet (P0 to P4),
  Project card (search field, projects grouped by organization, check on the current one),
  chat sheet with @-mention popover, the Model and Mode chips, and the session thread. The chat sheet shares the sheets' grabber
  and drag-down dismissal (`useSheetDrag`), on its header only, so a drag never competes with the thread's scroll.
- **Sign-in** and **Settings**: minimal, built from the same tokens. Settings keeps its Back chip on blurred floating chrome; the
  large title scrolls up into the chrome beside the chip, shrinking to section-header size (`SettingsChrome`, `collapsingTitle`).
