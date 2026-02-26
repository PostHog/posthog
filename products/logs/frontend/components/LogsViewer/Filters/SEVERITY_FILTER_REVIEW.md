# Severity level filter UX review

## Current implementation

The existing `SeverityLevelsFilter` (in `SeverityLevelsFilter.tsx`) uses `LemonMenu` + `LemonButton` to render a multi-select dropdown.

### What works

- `closeOnClickInside={false}` keeps the menu open for multi-select,
which is the correct behavior for this kind of filter.
- The display text collapses to "All levels" when nothing is selected
or everything is selected, which is a sensible default.

### Problems

1. **Horizontal width grows unboundedly.**
When several levels are selected (e.g. "Trace, Debug, Info, Warn")
the button text stretches the trigger wider and wider.
`whitespace-nowrap` on the button makes this worse:
the button will never wrap, it just pushes sibling filters off-screen.

2. **Incorrect ARIA semantics.**
`LemonMenu` renders `role="menuitem"` on each option.
The W3C menu pattern is for *actions* (File > Save, Edit > Undo),
not for toggling selections.
A multi-select list of options should use `role="listbox"` on the container
and `role="option"` with `aria-selected` on each item.
Screen readers currently announce these as "menu items"
instead of "options, 3 of 6 selected".

3. **No visible checkbox indicator.**
LemonMenu's `active` prop adds a background highlight,
but there is no checkbox/check-mark affordance.
Users can't tell at a glance which items are selected
without reading the button label or memorizing the highlight color.

4. **Redundant filter icon.**
The `IconFilter` takes up space
but doesn't add information
when the button already reads "Info, Warn, Error" or "All levels".
The text *is* the signifier of the affordance.

5. **`ALL_LOG_LEVELS` is derived from `Object.values(options)`.**
`options` maps *keys* (severity level identifiers like `"trace"`)
to *display labels* (`"Trace"`).
`Object.values(options)` returns the display labels,
which are then cast to `LogMessage['severity_text'][]`.
This works today only because the labels happen to be capitalized forms
of the keys; a refactor that changes the display labels would silently break the comparison.

## Components considered

The codebase has a modern `lib/ui/` component layer
built on Radix primitives, recently adopted across error tracking, workflows, and other products.

### Option A: `DropdownMenu` + `DropdownMenuCheckboxItem`

- Built on `@radix-ui/react-dropdown-menu`.
- Provides `CheckboxItem` with `aria-checked` and keyboard navigation.
- Already used in error tracking (`StackTraceActions`).
- **Drawback:** Radix dropdown menu uses `role="menu"` / `role="menuitemcheckbox"`.
The WAI-ARIA menu pattern is semantically for *actions*,
not for *selecting values from a list*.
A screen reader would announce "menu item checkbox" rather than "option, selected".

### Option B: `PopoverPrimitive` + W3C listbox markup (chosen)

- Built on `@radix-ui/react-popover` for the container.
- Custom `<ul role="listbox" aria-multiselectable="true">` with `<li role="option" aria-selected>`.
- Follows the [W3C Listbox pattern](https://www.w3.org/WAI/ARIA/apg/patterns/listbox/) exactly.
- Screen readers announce "option, 3 of 6 selected" — the correct semantics for a multi-select filter.
- Keyboard navigation (Arrow, Home, End, Enter/Space, Escape) implemented manually.

### Shared primitives

- **`ButtonPrimitive`** (`lib/ui/Button/ButtonPrimitives.tsx`) — the new standard trigger button.
- **`MenuOpenIndicator`** (`lib/ui/Menus/Menus.tsx`) — chevron that rotates on open/close.
- **`PopoverPrimitiveContent`** (`lib/ui/PopoverPrimitive/PopoverPrimitive.tsx`) — styled popover panel with `primitive-menu-content` class.

## Implemented: `SeverityLevelsDropdown`

New file: `SeverityLevelsDropdown.tsx`. Changes in existing files limited to `SeverityLevelsFilter.tsx` (swapped the body to delegate to the new component).

### Trigger

- `ButtonPrimitive size="sm" variant="outline"` — matches the height and border style of sibling filter buttons.
- `aria-haspopup="listbox"`, `aria-expanded`, `aria-controls` — links trigger to listbox.
- `aria-label` announces selection count (e.g. "Severity levels: 3 of 6 selected").
- Display text is fixed-width:
  - 0 or 6 selected → "All levels"
  - 1 selected → the level name (e.g. "Error")
  - 2+ selected → "{count} levels"
- No icon. `MenuOpenIndicator` chevron on the right signals the dropdown affordance.

### Listbox panel

- `<ul role="listbox" aria-multiselectable="true" aria-label="Severity levels">`.
- Each `<li role="option" aria-selected tabIndex="-1">` with a check icon when selected.
- Styled with the same CSS variables as `ButtonPrimitive menuItem size="sm"` for visual consistency.
- Clicking an option toggles it without closing the popover (Radix popover does not auto-close on content click).

### Keyboard navigation

| Key | Behavior |
|-----|----------|
| Arrow Down / Up | Move focus between options (wraps) |
| Home / End | Jump to first / last option |
| Space / Enter | Toggle the focused option |
| Escape | Close the popover |
