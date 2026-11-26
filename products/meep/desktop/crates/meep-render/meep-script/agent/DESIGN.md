# Native View design system

Start with the native elements and semantic theme tokens in the script guide. Fetch it with `design_system(topic="script")`. The tracker example is available with `design_system(topic="example")`.

## Foundations

System font. 18 px semibold view titles, 13 px body, 11.5 px secondary text. Line height 1.5 for reading, 1.35 for titles. Menlo 11.5 for identifiers. Use native component defaults and semantic theme colors: `ink` for main text, `secondary` for metadata, `tertiary` for decorative/disabled details, `canvas` for the reading surface, `inset` for recessed regions, and `rule` for separators. The user controls these colors; never assume white surfaces, dark text, or grayscale chrome. Use status colors sparingly and always pair color with a label or icon.

Spacing 4, 8, 12, 16, 20, 24, 32, 40, 48, 64 px. Use 24 px page insets, and 16 px inside narrow panels. Text measures <=720 px. Use 32 px controls, 28 px icon controls, 56 px two-line data rows, 6 px control radii. Use explicit pixels: they keep the host and views aligned. Glass belongs to navigation; reading surfaces remain opaque. No decorative gradients, shadows (shadows mark floating layers only), card grids, dashboard metrics, or repeated containers. Use one quiet list, a focused editor, or a purposeful split.

## Theme contract: roles, not literal colors

| Purpose                          | Token / component                                                    |
| -------------------------------- | -------------------------------------------------------------------- |
| Main reading surface and text    | `canvas` + `ink`; prefer `Page`, `Reading`, `Text`                   |
| Supporting text                  | `secondary`; prefer `Caption`                                        |
| Recessed surface or selected row | `inset` / `selected`, with `ink` text                                |
| Border or divider                | `rule`                                                               |
| Primary action                   | Native `Button`; custom accent fills require `accentForeground` text |
| Error / success                  | `danger` / `positive`, with explicit wording or an icon              |

Pass token names directly as style props. Never resolve a token to today's hex value or cache a palette in view state. Native elements resolve their defaults at paint time, including already-installed views. Literal brand/content/chart colors are deliberate exceptions, not a way to style the surrounding UI. Explain an intentional exception when validation warns about it.

When improving an existing view, inspect its current source first. Replace presentation literals by their role, not by a global hex substitution: the same white may be a reading surface, text on a colored action, or part of an image. Preserve the view identity, data, commands, selection and drafts. Do not rewrite unrelated views or migrate live user data just to change appearance. Verify the affected loading, error, selected and populated states. Check both light and dark appearances when the user has made them available; do not change the user's global theme for verification. Say which appearances were actually checked.

Theme compatibility and visual quality are separate checks. Before adding styling, identify the main task, primary content, and primary action. Give the content the most space. Use one clear heading, align labels and content on shared axes, and vary spacing to distinguish groups. Avoid repeating the same framed miniatures, adding a label to an already obvious region, or using tiny text to squeeze an overloaded composition into the window. A theme changes color; a design pass must still fix hierarchy, density, and layout.

## Elements

`Page`, `Reading`, `Header`, `Row`, `Column`, `Box`, `Scroll`, `Card`, `Heading`, `Text`, `Caption`, `Mono`, `Label`, `Badge`, `Link`, `ListRow`, `List`, `Button`, `IconButton`, `Notice`, `Empty`, `Loading`, `ErrorMessage`, and the form elements in `SCRIPT.md`. `SCRIPT.md` lists every prop.

Every element accepts style props for spacing, size, color and type. IDs must be stable, unique within their parent, and meaningful (`queue-title`, `pr-42`, `note-editor`), so selection references can point back to source. Put full truncated data in a tooltip or detail view. Trailing controls never shrink (`shrink: false`); text columns that should truncate use `truncate` or `grow`. Variable reading text wraps; list metadata truncates. Never truncate numeric comparisons. Fixed row heights must match the virtualized list.

## Behavior

Give inputs stable IDs. Keep drafts, filters, local selection and bounded cached rows in script state. The embedding host determines its lifetime. In Topics, load durable data through the source bridge when the script mounts. Keep the last good data while refreshing or showing errors. Never call the host or do heavy work from `render`. Use `List` for long collections, bounded requests and real MCP/CLI JSON. Keyboard focus and accessible names are required. No animation for frequent keyboard operations. Native hover/press feedback is immediate. Generated views are embedded; never draw host window chrome or a second sidebar of application navigation.

## Quality check before returning

Apply bundled Emil design guidance, Apple interaction guidance, and break-ui catalog. Verify empty, one item, 1,000 items (virtualized), realistic long names/URLs, Unicode, missing data, loading, denied access and errors. Check at narrow canvas width beside the agent. Preserve full values in detail/tooltips, keep actions reachable and focus visible. Report actual checks, never claim screenshot testing you did not perform. Add dev fixtures through data boundaries, never alter production data for a demo.

Shared sizes: 6 px control radius, 8 px surface radius, 28 px icon hit targets, 11.5 px mono and 11 px small text.

Use `Tabs` for tab sets. View adds roving focus, Left/Right, Home/End and Enter/Space activation.

## Hierarchy and density

Borrow Linear’s precision, not its navigation: a quiet 30 px sidebar row, medium-weight selection, and a single opaque content surface with a 6 px outer inset and 8 px radius. Inherit shell colors from the active theme. No extra header above a generated view. Draw outlines to separate adjacent regions or identify editable controls; do not nest framed panels inside framed panels.

Align headings, form labels and collection rows on the same 24 px leading axis. Use whitespace between sections, hairlines between records. Main content has the strongest contrast; metadata uses the secondary token. Use `Tabs({ underline: true })` for page navigation and default segmented tabs for a local mode. Both keep native roving keyboard focus.

Keep row actions on the selected row or in its detail, rather than revealing them on hover. Reserve their width so labels never jump. Do not hide primary actions, pending approvals, or running-state controls.

Chat uses one continuous reading surface, a compact inset composer, subdued user messages, and unboxed assistant responses. Tool output expands along a single vertical guide. Permission decisions keep their explicit action buttons and scope. Avoid animation on hover, keyboard navigation, streaming text and live source updates.

Record editors use `Form` and `Field` (440 px), which provide a complete consistent pattern aligned to the page axis. Long exact values (paths, IDs) use `ReadOnly`, which keeps a Copy action. Never silently clamp operational values. Use `Header` to group a title, useful data context and trailing refresh action. Avoid decorative taglines. A selected-record detail must be bounded and scrollable so it cannot consume the whole collection. Empty saved sessions and an empty workspace need an explanatory state and a clear next action.

## Forms: use the complete pattern

Read the form section of `design_system(topic="script")` before building an editor. The form kit supplies native 32 px inputs, a bounded scrolling textarea, labeled fields with optional hints/validation, a dropdown trigger, compact immutable metadata, and a save/discard row. Constrain the **whole form** to 440 px; do not stretch individual controls across a wide window. Keep a 6 px label gap and 18 px between fields. Sections provide hierarchy, not additional cards.

Native controls must look editable: a visible neutral border, readable text, adequate vertical padding, and visible keyboard focus. Inputs have a fixed native height. Size a `Textarea` with `rows`.

A field label belongs immediately above its control. Show Optional beside the label only when it helps; do not add a separate Required/Optional paragraph below every field. Hints explain format or consequences. Show a specific error when validation fails, focus the first invalid field, and retain the user's input. Immutable IDs belong in a compact metadata row with Copy, not a large form section. Use a dropdown for a short named category and a content-sized segmented control for three mutually exclusive statuses. Keep Save and Discard within the same form measure; ensure they remain reachable at short heights.

The `record` example saves locally and says so. For remote writes, add explicit saving/success/failure state around the permitted source request. Local draft persistence must never be described as a successful remote save. Preserve unknown record fields and edits typed during an in-flight request.
