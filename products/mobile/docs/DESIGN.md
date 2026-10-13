# Design

The design handoff (README, prototype and reference screenshots) is the spec.
This file records how it maps to React Native.

## Tokens

All values live in `src/ui/tokens.ts`. Styles use `StyleSheet.create` with these values.

- `colors`: every color in the handoff, named by role (`ink`, `muted`, `secondary`, `tertiary`,
  `border`, `hairline`, `rowDivider`, `sunken`, `pressed`, `background`, `orange`, `blue`, ...),
  plus the scrims and the white overlays used on the orange button.
- `avatarPalette`, `accentColor`, `sparklineHotColor`: keyed by the report `Accent`
  (`alert` orange, `opportunity` blue, `resolved` ink).
- `type`: the type scale. React Native letter spacing is in points, so `letterSpacing(size, em)`
  converts the handoff's em values per size. Text without an explicit line height uses the
  prototype's root line height of 1.4 (`lineHeight(size)`).
- `fonts.mono`: Menlo on iOS, `monospace` on Android, the handoff's CSS stack on web.
  Everything else uses the system font.
- `space` (keyed by value, `space[14]`), `radii`, `layout` (gutters, 44pt tap target, and the
  prototype frame's 54pt status bar and 34pt home indicator).
- `shadows`: `shadow*` props plus Android `elevation` on native (radius is half the CSS blur);
  the exact CSS `boxShadow` on web.
- `motion`: 180ms fades, 200ms sheets and chevron, 220ms floating cards, with the handoff's
  bezier curves. `usePresence` sets every duration to 0 when reduce motion is on.
- `inputReset`, `prettyWrap`: web-only fixes, see below.

## Reading handoff values

- **Box sizing.** The prototype's `div`s use CSS `content-box`, so a `height` or `min-height`
  excludes padding and border. React Native is always border-box. Where the two differ, the code
  uses the rendered size and says so in a comment: inbox rows render 71pt (44pt content), icon
  tiles 40pt, the bottom nav pill 64pt, the Chat button 56pt, the Back chip and Prev/Next pill
  46pt, the action pill 54pt, the hand-off agent row 78pt, the dashed "No assignee" avatar 36pt,
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
| `BottomSheet` | `ui/BottomSheet.tsx` | Grabber, radius 22, slides up 200ms, closes on scrim tap or a downward drag |
| `FloatingCard` | `ui/FloatingCard.tsx` | Radius 28 card, scales from 0.92 and drops 6pt, 220ms emphasized curve |
| `ReportContextMenu` | `features/inbox/ReportContextMenu.tsx` | Inbox row long-press menu on `FloatingCard`; nav menu width; opens 8pt below the row, or above it when the bottom bar is in the way (`contextMenuPlacement.ts`) |
| `ReportMeta` | `features/report/ReportMeta.tsx` | Byline under the lede (source glyph and label · "Since …"), then the Owner and Priority chips: 32pt bordered pills with a chevron that open the Assignee card and the Priority sheet. No owner shows a dashed orange circle and "Assign"; P0 and P1 color their code orange |
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
  dimmed in demo mode. A long press on a row (or the screen reader's "Show report actions") opens a menu
  with Reassign, Snooze, Chat and, for an unread report, Mark as read; each does what the report's
  action pill does, without leaving the inbox. Loading, empty and error states are separate screens.
- **Chats**: the mobile port of the web app's Chats pane. Header with the logomark, "Chats" and a
  New chat button. A search field above the list filters titles on the device. Rows are grouped
  under day labels (Today, Yesterday, a weekday, a date, Earlier) and use the inbox row geometry:
  a chat bubble tile for a PostHog AI chat, a branch tile with a status dot for a sandbox session.
  A chat row opens the chat sheet on that conversation. A session row opens the session in the web
  app, and is dimmed in demo mode. The nav pill shows Chats selected. Loading, error, empty and
  "No matches" are separate screens; when one of the two sources fails, a line above the list
  says so and offers Try again.
- **Nav menu**: project name (opens the Project card), Inbox (selected), Settings, Sign out.
- **Report**: top chrome, headline, lede, the byline with the Owner and Priority chips (`ReportMeta`),
  evidence (trace, quotes, replay), facts, sparkline, activity, and the action bar.
- **Action bar** (`actionBarStateFor`): `idle` (Hand off to PostHog + chevron),
  `handed` (dark "PostHog is on it" card), `decision` (NEEDS YOUR DECISION card, collapsible),
  `decided` (dark card with the answer and Undo), `pr_ready` (READY FOR REVIEW card with one
  full-width Review PR button), `resolved` (action pill only). The Reassign / Snooze / Chat pill
  shows in every state.
- **Overlays**: hand-off sheet, snooze sheet (with a custom time picker), Assignee card, Priority sheet (P0 to P4),
  Project card (search field, projects grouped by organization, check on the current one),
  chat sheet with @-mention popover and a simple thread. The chat sheet shares the sheets' grabber
  and drag-down dismissal (`useSheetDrag`), on its header only, so a drag never competes with the thread's scroll.
- **Sign-in** and **Settings**: minimal, built from the same tokens. Settings keeps its Back chip on blurred floating chrome; the
  large title scrolls up into the chrome beside the chip, shrinking to section-header size (`SettingsChrome`, `collapsingTitle`).
