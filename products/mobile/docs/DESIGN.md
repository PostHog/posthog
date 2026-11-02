# Design

The design handoff (README, prototype and reference screenshots) is the spec.
This file records how it maps to React Native.

## App icon

Android adaptive icon layers use a 108dp canvas, with a central 72dp viewport and a 66dp safe circle.
`plugins/withAndroidAdaptiveIconInsets.js` adds a proportional 18dp inset on every side during
prebuild, so the hedgehog and the DEV or PREVIEW label fit inside launcher masks. The inset
applies to both regular and round adaptive icons for all three build variants.

Keep the 1024px source images at their existing scale; the plugin supplies Android's extra
spacing. Icon changes need a new native build and cannot ship through an over-the-air update.
See [Android's adaptive icon guidelines](https://developer.android.com/develop/ui/compose/system/icon_design_adaptive).

## Tokens

The app follows the device's light or dark setting unless the Appearance setting in Settings picks Light or Dark; `useColorSchemeName` combines that override (`appearanceStore`) with the device scheme.
`app.config.ts` sets `userInterfaceStyle: 'automatic'` and a dark splash, which take effect only after a native rebuild.
Scheme-independent values live in `src/ui/tokens.ts`. Colors and everything derived from them live in `src/ui/theme.ts`.

- `lightColors`, `darkColors`: every color in the handoff, named by role (`ink`, `muted`, `secondary`, `tertiary`,
  `border`, `hairline`, `rowDivider`, `sunken`, `pressed`, `background`, `orange`, `blue`, ...),
  plus the scrims and the overlays used on the accent button. Both palettes have the same keys.
  The dark palette follows the web app's dark theme: cool dark neutrals, light text, amber accent.
- Roles that were all white in the light handoff have their own tokens, because they differ in dark:
  `surface` for cards, pills, sheets, floating cards, text fields and menus;
  `onInk` for text and icons on an `ink` fill; `onAccent` for text and icons on an `accent` fill.
  `white` is literal white in both schemes, only for text on a fixed color, such as avatar initials.
  The logomark's head and the wordmark use `ink`, so they stay visible on a dark background.
- `accent` (`accentHover` when pressed) fills the primary call to action: Sign in, Hand off, Send a decision.
  `orange` stays for warnings, failures, destructive actions, the P0/P1 priority and the report `alert` accent.
- Some roles shared `border` or `ink` in light but need their own value in dark:
  `switchOn`/`switchOff` for switch tracks (the thumb is literal `white`), `control` for unselected radio and checkbox
  rings, `disabledFill`/`onDisabled` for a disabled primary button and its label, `barNeutral` for single-series bars
  and `terminalBorder` for the code card outline (transparent in light).
- `useTheme()` returns the current `Theme`: `colors`, `shadows`, `avatarPalette`, `accentColor` (keyed by the report
  `Accent`: `alert` orange, `opportunity` blue, `resolved` ink), `swipeColors`, `chartPalette` and
  `previousPeriodColor`. `useColors()` returns only `colors`. `useColorSchemeName()` reads the device setting;
  an unknown setting counts as light.
- `createStyles(({ colors, shadows }) => ({ ... }))` replaces `StyleSheet.create` for any sheet that uses a color or a
  shadow. Call it at module level; it returns a `useStyles` hook that builds the sheet once per scheme. The factory
  must be pure. Code outside a component (a helper, a pure function) takes `ThemeColors` or the `Theme` as a
  parameter, or a sheet typed `ReturnType<typeof useStyles>`, and the component passes it in.
- Inline colors (`color`, `tintColor`, `stroke`, `placeholderTextColor`) come from `useTheme()` in the component.
  `BlurEdge` tints, `keyboardAppearance`, `StatusBar`, `ActivityIndicator` and `RefreshControl` follow the scheme.
- `environmentRibbonColors` (in `tokens.ts`) are brand bands and stay the same in both schemes.
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
- `shadows` (on the `Theme`): `shadow*` props plus Android `elevation` on native (radius is half the CSS blur);
  the exact CSS `boxShadow` on web. Dark shadows are black and stronger.
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

Views, Chats and browse lists use the shared `SearchField`.
Its 16pt input has an explicit 20pt line height, centered vertically without Android font padding, so placeholder and entered text keep the same alignment across screens.

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
- **Page titles.** Pushed pages share a 46pt navigation row and a 20pt gap before their title block.
  Their blur fade ends 10pt before the content. `screenLayout` supplies these offsets to every page.
  As the title scrolls under navigation, `ScreenChrome` fades in a smaller copy centered between the controls.
  The title truncates before either control and stays out of the accessibility tree; the content title remains the heading.
  This pattern covers Settings, browse lists, dashboards, insights, web analytics, scrollable full-screen charts,
  Errors, issues, Sessions, recordings, reports and full reports. Tab titles stay in their shared navigation row.
- **Text wrapping.** The prototype sets `text-wrap: pretty`. iOS gets the same behavior from
  `lineBreakStrategyIOS="standard"`, and web from the CSS property (`prettyWrap`).
  Android wraps greedily.

## Component inventory

| Component                             | File                                                       | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ------------------------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Pressable44`                         | `ui/Pressable44.tsx`                                       | Default 6pt hit slop so 34pt visuals reach 44pt; pressed and hover background; optional haptic                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `PillControl`                         | `ui/PillControl.tsx`                                       | White bordered pill for icon buttons                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `SegmentedPill`                       | `ui/SegmentedPill.tsx`                                     | Equal segments with inset dividers; `raised` adds the chip shadow; `selected` state                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `IconTile`                            | `ui/IconTile.tsx`                                          | Source icon tile, muted for resolved, dismissed, or snoozed reports                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `Avatar`                              | `ui/Avatar.tsx`                                            | Initials on a palette color picked from a seed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `MonoText`, `Eyebrow`, `Dot`          | `ui/`                                                      | Mono text, uppercase label with optional dot, colored dot                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `Scrim`                               | `ui/Scrim.tsx`                                             | Fades with the overlay; optional tap to close                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `BottomSheet`                         | `ui/BottomSheet.tsx`                                       | Grabber, radius 22, slides up 200ms, closes on scrim tap or a downward drag. An optional `scrollGesture` makes a drag that starts on an inner list scroll it instead                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `HandoffOptionRows`                   | `features/handoff/HandoffOptionRows.tsx`                   | White bordered group of 48pt rows in the hand-off sheet: muted label, right-aligned bold value with an optional tertiary second line, chevron                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `SheetPageHeader`                     | `features/handoff/SheetPageHeader.tsx`                     | 44pt round back button and sheet title for a page that replaces the sheet's content                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `ModelPage`, `ModePage`, `BranchPage` | `features/handoff/`                                        | Hand-off option pages; the chat's options sheet hosts Model and Mode too, so they take the options and pick callbacks as props. Model: "Reasoning" effort pills (ink fill for the picked or known default effort), then models under "Claude Code" and "Codex" eyebrows with the cost multiplier; the selected model, including an untouched default, has a tinted row, bold label and check. The list is capped at 42% of the window and scrolls without closing the sheet, followed by "Reset to default". Mode: label and description rows. Branch: bordered text field that lifts with the keyboard, one note and a Done button |
| `Composer` chips                      | `features/chat/Composer.tsx`                               | After `@`: a Model chip ("Default", or the pinned model without its "Claude" prefix and the effort, such as "Opus 5.5 · High") and a Mode chip ("Auto" by default). 32pt bordered pills with a chevron that reach 44pt through the hit slop, shrink and truncate to one line on a narrow phone, and dim while the agent works, the history loads, a send is in flight or a decision waits. On an open chat they start from the run's own model and mode, and the Model page lists only the run's harness                                                                                                                            |
| `ChatOptionsSheet`                    | `features/chat/ChatOptionsSheet.tsx`                       | `BottomSheet` over the chat that hosts `ModelPage` or `ModePage` for the chat's own options. The back button closes it, and a mode pick closes it. It draws inline, because the chat route is a native modal outside the overlay host                                                                                                                                                                                                                                                                                                                                                                                               |
| `FloatingCard`                        | `ui/FloatingCard.tsx`                                      | Radius 28 card, scales from 0.92 and drops 6pt, 220ms emphasized curve                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `HeaderMenu`                          | `features/views/screen/HeaderMenu.tsx`                     | The More menu of a pushed screen (Sessions and Errors lists, issue, session): a `FloatingCard` under the chrome's More pill with `MenuItem` rows and a trailing glyph                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `MetricChart`                         | `ui/chart/MetricChart.tsx`                                 | Line or bar chart on Skia (victory-native). The y axis floats for lines and starts at zero for bars. Hairline gridlines, 11pt mono ticks. Tap or drag to scrub, with a selection haptic and a tooltip that stays after release. 144pt high by default                                                                                                                                                                                                                                                                                                                                                                               |
| `ObservationCard`                     | `features/report/metrics/ObservationCard.tsx`              | White card: "Observation" eyebrow, title, caption, 28pt mono value, chart, then the window and filter count with Open insight                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `ImpactMetrics`                       | `features/report/metrics/ImpactMetrics.tsx`                | "Impact" eyebrow over a two-column grid of tiles: 20pt mono value, title, and the window or measured time. A tile with a link opens the insight                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `ReportCharts`                        | `features/report/metrics/ReportCharts.tsx`                 | "Charts" eyebrow over one card per chart: title, caption, the chart when the app can draw it, and Open insight                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `ReportContextMenu`                   | `features/inbox/ReportContextMenu.tsx`                     | Inbox row long-press menu on `FloatingCard`; nav menu width; opens 8pt below the row, or above it when the bottom bar is in the way (`contextMenuPlacement.ts`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `ReportMeta`                          | `features/report/ReportMeta.tsx`                           | `ReportByline` under the headline, above the lede, then the Owner and Priority chips: 32pt bordered pills with a chevron that open the Assignee card and the Priority sheet. No owner shows a dashed orange circle and "Assign"; P0 and P1 color their code orange                                                                                                                                                                                                                                                                                                                                                                  |
| `ReportByline`, `HeadlineTitle`       | `features/report/`                                         | The byline (source glyph and label · "Since …") and the 22pt headline with its number in the accent color, shared by the report screen and the full report                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `TextLinkRow`                         | `features/report/TextLinkRow.tsx`                          | Quiet 15pt ink link with a 14pt secondary chevron, or the external-link mark when it opens the browser. 32pt tall, so the hit slop reaches 44pt. No button chrome                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `ReportMarkdown`                      | `features/report/details/ReportMarkdown.tsx`               | The full report's markdown, on the shared parser in `lib/markdownIt.ts`. `summary` is 16pt ink with 17pt headings (`type.sectionHeader`); `signal` is 15pt. Fenced blocks are `MonoBlock`s, images are dropped, and `[label](chart:id)` reads as its label (`chartRefs.ts`)                                                                                                                                                                                                                                                                                                                                                         |
| `MonoBlock`, `SignalCard`             | `features/report/details/`                                 | A fenced block on the trace's dark card (`type.mono`); a white bordered card per signal: source glyph, label, time and ticket number, then the content and Watch session                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `Sparkline`                           | `ui/Sparkline.tsx`                                         | 14 bars; height `max(2, round(v × 32 / max))`, capped at 32 (`sparklineMath.ts`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `TimelineItem`, `RichText`            | `ui/`                                                      | Activity entry with node, connector, `**bold**` text, via chip and time                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `FadeEdge`                            | `ui/FadeEdge.tsx`                                          | SVG gradient behind floating chrome (no gradient dependency)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `BlurEdge`                            | `ui/BlurEdge.tsx`                                          | Masked blur of the content under floating top chrome                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `BackChip`                            | `ui/BackChip.tsx`                                          | Report and Settings back button                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `EnvironmentRibbon`                   | `ui/EnvironmentRibbon.tsx`                                 | 28pt band above the sign-in logo and under the Settings title: amber for dev builds, purple for preview builds, red for a store build on a host that is not PostHog Cloud. Hidden in a store build on Cloud. Colors in `environmentRibbonColors`, text from `environmentBadge()`                                                                                                                                                                                                                                                                                                                                                    |
| `StateView`, `LoadingView`            | `ui/StateView.tsx`                                         | Empty and error screens with a next action; loading spinner                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `PostHogLogomark`, `PostHogLogo`      | `ui/icons/PostHogLogomark.tsx`, `ui/icons/PostHogLogo.tsx` | Brand logomark and landscape lockup as SVG, sized by `height`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| Icons                                 | `ui/icons/*.tsx`                                           | One component per glyph, ported from the prototype's SVG paths                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |

## Screens and states

- **Splash**: the centered gradient logomark hops in a ripple, with the head first and the three colored spikes following.
  It uses a gentle 720ms hop every 1.4 seconds, with 45ms between parts and a smooth start and landing.
  All four parts share one animation clock, and the logo stays still with reduced motion enabled.
  The native launch screen fades into this animation once the animated splash lays out.
  The splash stays above the app until the session and first screen are ready, with the existing eight-second inbox timeout.
- **Tabs header** (`features/tabs/TabsHeader.tsx`): Inbox, Chats and Views share one header that the
  tabs layout draws once, like the bottom bar. The logomark and the tab's title sit at the same spot on
  every tab. The pill on the right holds More on every tab, and a filter button left of it on a tab that
  publishes one (the Inbox); Views in Edit pins swaps the pill for Done. Pull to refresh is the only manual
  refresh, so the header has no refresh button. A tab may add a status line under the title (Views does); it
  and the refresh hint are absolutely positioned, so they never move the title row. Each screen publishes its
  refresh hint, status line, filter button and menu rows to its own slot in `tabHeaderStore` with `useTabHeader`, and the header reads the focused tab's slot.
  The logomark plays the splash's hop while the focused Inbox, Chats or Views page refreshes, including pull-to-refresh and automatic refreshes.
  It finishes its current hop when refreshing ends and stays still with reduced motion enabled.
- **Inbox**: rows (source · `#123` PR tag when the report has a PR, green when open, purple when merged, gray otherwise · time),
  pull to refresh, floating nav pill (Home selected,
  Chats, Products) and the Chat button. Chats in the pill opens the Chats screen; the Chat button
  opens a new chat sheet. Products opens the project's product library in the web app, and is
  dimmed in demo mode or when the session has no project. A long press on a row (or the screen
  reader's "Show report actions") opens a menu with Hand off to the saved agent (PostHog,
  Claude Code or Codex), Reassign, Resolve, Dismiss, Chat and Mark as read (for an unread report) or Mark as unread.
  A full swipe on a row changes its read state: swipe right past 30% of the row marks the report read (blue),
  swipe left marks it unread (ink). Both directions always play, and a swipe toward the state the row already has
  only plays the animation. Screen readers get the same change as a "Mark as read" or "Mark as unread" row action.
  Unread reports have a bold title and an 8pt blue dot at the right. Read reports use a regular-weight title
  without the dot. Resolved, dismissed, and snoozed reports keep their muted styling.
  Hand off uses the same eligibility rules and saved destination as the report's hand-off button;
  it waits for report details, blocks repeat taps while pending and keeps failures in the menu for retry.
  A report with a pull request shows View PR (with an external-link mark, it opens the browser) in
  place of Hand off, from the first frame: the inbox list payload carries the PR URL, so the menu
  does not wait for report details.
  The other actions work like the report's action pill, without leaving the inbox.
  The header's filter button opens the Filter and sort sheet (`InboxFilterSheet`). Sort by is one outlined white card of 56pt rows with a leading icon and hairline dividers; the selected row has a gray fill and a check mark.
  Created is a `SegmentedPill` (Any, 24h, 3d, 7d, 14d), and Sources are wrapping chips with a checkbox, outlined in ink when on. The list fades out at the bottom of the sheet.
  A choice applies at once, Clear resets them all, and a blue dot on the button shows that a filter or sort is on.
  Loading, empty, "No reports match these filters" (with Clear filters) and error states are separate screens.
- **Chats**: the mobile port of the web app's Chats pane. A search field above the list filters titles on the device. Rows are grouped
  under day labels (Today, Yesterday, a weekday, a date, Earlier) and use the inbox row geometry:
  a chat bubble tile for a PostHog AI chat, a branch tile for a report hand-off or another session,
  and an origin label, a status dot and the time under the title. A row opens the chat sheet on that
  task: the agent's thread, its PR card, and a pending decision above the composer. The nav pill
  shows Chats selected. Loading, error, empty and "No matches" are separate screens.
- **Nav menu** (More in the tabs header): project name (opens the Project card), then on Views a section with
  Edit pins, then Settings and Sign out.
- **Report**: top chrome, headline, the byline with the Owner and Priority chips (`ReportMeta`), lede,
  "Read the full report" (only when there is a summary or a signal), evidence (trace, quotes, replay), facts,
  the observation card, impact tiles, charts, activity, and the action bar.
- **Full report** (`report/[id]/details`): top chrome with Back only and the headline as its scroll title,
  a "Full report" eyebrow, the headline and the byline, the whole summary, then "Signals" with a count and one card per
  signal, newest first, and "Open in PostHog" at the end (hidden in demo mode).
  Charts stay on the report screen, so the summary's chart references read as their labels and a paragraph of references only is dropped.
  Loading, "Couldn't load this report" with Try again, and "This report has no more detail yet." are separate states.
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
  implementation chat. The Reassign / Resolve / Dismiss pill and the round ink Chat button to its right
  show in every state; Chat starts report discussion.
  Its compose icon matches the tabs' Chat button.
  Resolve and Dismiss open a sheet with the web
  inbox's reasons and an optional note, and after a confirmed verdict the screen goes back to the inbox.
  A 409 from the server (the report's status cannot take that verdict) stays in the sheet as an error. Undo is a separate action while an answer is in flight. Transient tool text
  clears when a turn is idle or terminal and stays on one truncated line while active.
- **Assignee card**: loads the latest complete reviewer assignment, including when it is older than the first page of activity. On the report screen, opening it shows loading until that assignment is known, or an error with a retry action if the read fails. Search and unsaved selections stay in place while the report refreshes. Closing and reopening starts from the current assignment.
- **Overlays**: hand-off sheet, Resolve and Dismiss sheets (`VerdictSheet`), Assignee card, Priority sheet (P0 to P4),
  Project card (search field, projects grouped by organization, check on the current one),
  chat sheet with @-mention popover, the Model and Mode chips, and the session thread. The chat sheet shares the sheets' grabber
  and drag-down dismissal (`useSheetDrag`), on its header only, so a drag never competes with the thread's scroll.
- **Sign-in**: the logo, form and account link are vertically centered above the legal footer. Privacy policy and Terms sit at the bottom safe area. The page scrolls when the form needs more room, including with the keyboard open.
- **Settings**: minimal, built from the same tokens. The large title scrolls with the content.
  A centered title fades into the navigation row as the large title scrolls out, using the shared page-title pattern.
  Groups run Start page, Project, Notifications, Appearance, Demo (dev builds), App, Account, Environment (internal builds), Legal, then Sign out.
  Start page, Project and Appearance use the same radio rows (`SettingsRadioRow`).
  The project list puts the current project and its organization first, with the other projects alphabetical
  within each organization. It initially shows five projects in total. See more expands the full list,
  and See less collapses it again. Organization labels stay visible for accounts with multiple organizations.
  Appearance is Match system, Light or Dark, saved on the device; screens wait for it to load so they never paint in the wrong scheme.
  Start page picks the tab the app opens on (Inbox, Chats or Views) and is saved on the device (`defaultPageStore`).
  Sign in also lands there, and so do Back on Settings or a view and closing the chat when there is no screen to go back to.
  Until the person picks one, the app saves a start page once, on the first launch that knows whether the selected project's organization approved AI data processing: Views if it did not, Inbox if it did.
  While that status is unknown, the app opens the inbox and saves nothing.
- **Errors list** (`features/errors/ErrorsListScreen.tsx`): one body in two chromes. Pushed from the Views Browse
  row, it draws the Back chip and More over a 28pt "Errors" title and the "Most users first · updated 5m ago" line; as
  a pinned tab, the tabs header draws the title and that line. Under them sit the 24h and 7d `SegmentedPill` and the New,
  Spiking and Mine chips (ink fill when on; tapping the chip that is on clears it). Rows follow the inbox geometry:
  the exception type on one line with a New (orange outline) or Spiking (orange fill, up arrow) badge, the exception
  value in secondary text, then the owner's avatar, users and first seen in tertiary text. The list loads 15 issues
  per page with a Load more footer; charts stay on the issue detail. Pull to refresh reloads the first page.
  Loading (row-shaped blocks), "Couldn't load your
  errors" with Try again, the empty state per filter with its next step ("Show the last 7 days", "Show all active
  issues"), the Views sign-in state for missing scopes, and a demo state are separate screens. New and Spiking show
  "No matches in loaded issues" while more pages remain. Pending spike reads show "Checking for spikes…"; failed
  reads offer Try again. More (pushed only)
  holds Pin to navigation or Unpin from navigation, with the Views toast and Undo, and Open on web.
- **Issue** (`features/errors/IssueScreen.tsx`): Back and More on the floating chrome. "Error · project" eyebrow,
  the status chip (the web's labels and colors: amber Active, green Resolved, red Suppressed) and the New or Spiking
  badge; the 22pt headline with the exception type in orange; a clock byline with first and last seen; the owner chip
  (dashed orange "Assign" when nobody owns it). Impact: the 24h and 7d segment, three tiles (users, sessions,
  occurrences with a mono "last 24h"), and a card with the window's volume line and the trend caption ("Up 45%",
  orange while rising). Release: version, short commit, branch and library, with "First seen in this release" when the
  first and latest releases match. Where it breaks: the dark trace card from the report (exception, innermost in-app
  frame, "In-app frame 1 of 4" and Show all, up to three frames), then path, browser, OS and app version shares as text
  and a stacked bar. Sessions: up to three rows ("Chrome on macOS", "Error 12m ago") that open the session screen.
  Inbox report: the report built from the issue, when there is one. The bottom bar is the report's layout: a pill with
  Resolve and Suppress, or Reopen when the issue is not active, and the round ink Chat button. Resolve and Reopen show
  the Views toast with Undo; Suppress opens a confirmation sheet first. More holds Assign, Open on web and Copy link.
  The Assign sheet offers Assign to me (or Unassign me) and Assign a teammate on the web.
- **Sessions list** (`features/replay/ReplayListScreen.tsx`): one body in two chromes, like the Errors list. Pushed
  from Views, Back and More over a 28pt "Sessions" title and "Newest first · last 7 days";
  as a pinned tab, the tabs header draws both. Rows: an 80 × 50 frame (the scan's
  thumbnail, or a muted recording tile), the scan's title, or "Session · 14 clicks · 1 error" in regular weight for
  an unsummarized one, then person, length, "key moment 2:14" and the time ago (never the raw score), with an
  orange dot when the recording logged console errors. A row opens the session at its key moment. The list loads
  10 recordings per page with a Load more footer. Up to 5 optional recommendations load afterward under Worth watching,
  below the recordings; recommendations matching loaded recordings enrich those rows without moving them.
  Pull to refresh reloads the first page and the recommendations.
  Loading (row-shaped blocks), "Couldn't load your sessions" with Try again, "No recordings yet", the sign-in state and
  the demo state are separate screens. More (pushed only) holds Pin to navigation or Unpin from navigation, with the
  Views toast and Undo, and Open on web.
- **Session** (`features/replay/SessionScreen.tsx`): Back on the left; on the right one pill with the "Open full replay" icon
  (the only way to the web player) and More (Share link at m:ss, Copy session ID). "Session · project" eyebrow, the 22pt
  title (the scan's, else one built from the events), the meta line (person · date and time · length · browser on OS),
  then a "Key moment 2:14" chip in orange (it opens that chapter's frame) or "First error 2:14", and a city chip.
  The Summary card holds the summary text, the worth-watching bars with "Worth watching" and the reason (no raw score), and "Replay Vision ·
  scanned …" in mono. Its other states: a spinner while loading, "No summary yet" with Summarize this session and
  "Uses Replay Vision credits", "Summarizing" with a spinner, "Still working" with Check again, "AI summaries are off for
  this organization" with a lock, and "Couldn't load the summary" with Try again. Chapters: a 96 × 60 frame, the mono
  start time and the title per row; the key moment's row has an orange rule and flag. A row opens the frame sheet: the
  frame at full width, the chapter title, "Chapter 4 of 5 · 2:14", the Key moment chip, Previous and Next, and "Frames
  can show text that the recording did not mask." What happened: the event count, minute labels, and `TimelineItem`
  rows with the event name as the chip and the offset as the time; errors and rage clicks draw in orange, and an error
  with an issue opens it. The round ink Chat button sits bottom right. Loading is a skeleton of the screen; "Couldn't
  find this recording" (expired or deleted) and "Couldn't load this session" are separate states.
