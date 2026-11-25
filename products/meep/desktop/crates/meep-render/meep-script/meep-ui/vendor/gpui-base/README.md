# gpui-base

[![Crates.io](https://img.shields.io/crates/v/gpui-base.svg)](https://crates.io/crates/gpui-base)
[![Documentation](https://docs.rs/gpui-base/badge.svg)](https://docs.rs/gpui-base)
[![License](https://img.shields.io/crates/l/gpui-base.svg)](../../LICENSE-APACHE)

`gpui-base` is the reusable foundation of the [GPUI Component](https://github.com/longbridge/gpui-kit) Rust desktop application framework, built on GPUI. It is intended for applications that want to build and own their own design systems. It provides interaction behavior, focus management, accessibility semantics, animation, virtual lists, theme tokens, and other foundational capabilities without imposing a visual style.

> Use [`gpui-component`](https://crates.io/crates/gpui-component) if you want ready-to-use components with a complete visual design. Use `gpui-base` if your application should own its component source and visual styles while reusing stable, shared behavior.

## Where It Fits in GPUI Component

GPUI Component is the framework and project brand. Its currently implemented
architecture has two directly usable layers:

```text
application
├── gpui-component     Complete, styled framework experience
└── custom UI          Application-owned design system
         └── gpui-base Interaction, state, and infrastructure (this crate)
```

Dependencies always point from higher layers toward the foundation: `gpui-base` does not depend on `gpui-component`. Existing applications can continue using `gpui-component`; a direct dependency on `gpui-base` is only necessary when building custom components or a design system.

## Relationship to the shadcn Ecosystem

The GPUI Component ecosystem follows the same layering idea as [shadcn](https://ui.shadcn.com):

| GPUI ecosystem                       | shadcn ecosystem               |
| ------------------------------------ | ------------------------------ |
| GPUI                                 | HTML + Tailwind CSS            |
| `gpui-base`                          | [Base UI](https://base-ui.com) |
| `gpui-component`                     | shadcn                         |
| `crates/component` in GPUI Component | shadcn's default UI            |

## Design Principles

- **Behavior belongs to the foundation:** click handling, keyboard activation, controlled state, focus, accessibility roles, and infrastructure.
- **Presentation belongs to the application:** layout, size, color, spacing, radius, borders, shadows, variants, and animation are defined by the application or a higher-level component.
- **Applications own their components:** foundation controls can be freely composed and modified without adopting a fixed visual language.
- **Semantic APIs come first:** themes expose tokens such as `primary`, `surface`, and `destructive` instead of accumulating component-specific fields.
- **GPUI-native composition:** controls implement GPUI interfaces such as `Styled` and `ParentElement` and work with GPUI's fluent builder API.

For example, `Button::new("save")` has no padding, background, radius, or size by default. Being unstyled is an explicit API contract, not a missing feature.

## Installation

Depend on `gpui-kit`, which pins the GPUI crates `gpui-base` was built
against and re-exports them as `gpui_kit::gpui` and `gpui_kit::platform`, with
`gpui-base` itself always available at `gpui_kit::base`. Turn off the default
features to skip the styled layers:

```toml
[dependencies]
gpui-kit = { version = "0.7", default-features = false }
```

If Cargo reports incompatible GPUI types, check whether your application pulls
GPUI in from somewhere other than `gpui-kit`.

### Optional Features

| Feature     | Enabled by default | Purpose                                                    |
| ----------- | ------------------ | ---------------------------------------------------------- |
| `inspector` | No                 | Enables inspector support in both `gpui` and `gpui_macros` |

## Initialization

Call `gpui_kit::base::init(cx)` once before creating windows or using foundation controls. It installs the global theme and focus-trap infrastructure required by the base layer.

```rust
use gpui_kit::*;

fn main() {
    gpui_kit::application().run(|cx| {
        gpui_kit::base::init(cx);

        // Create windows and views after initialization.
    });
}
```

If the application already calls `gpui_kit::init(cx)`, do not call `gpui_kit::base::init(cx)` again. The higher-level initializer includes base initialization.

## Retained Rich-Text Selection

Managed `TextViewState` retains completed logical selections and their Copy
payload across style, syntax-highlighting, font, and width changes by default.
Current styles and wrapping still apply; an old pointer rectangle is not used to
reconstruct the selection after reflow. Later outer-layout origin changes also
preserve the selected text. A new selection gesture or explicit clear replaces
or clears the selection normally.

Replacing the source or Markdown parser configuration still invalidates selection.
The owning view must retain the state and its painted selection participant; this
behavior does not pin rows unmounted by an outer virtual list.

## Quick Start

Foundation controls can be styled and given children like ordinary GPUI elements:

```rust
use gpui_kit::prelude::*;
use gpui_kit::{Context, IntoElement, Render, Window, px, rgb};
use gpui_kit::base::Button;

struct SaveButton;

impl Render for SaveButton {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        Button::new("save")
            .px_3()
            .py_2()
            .rounded(px(6.))
            .bg(rgb(0x2563eb))
            .text_color(rgb(0xffffff))
            .accessibility_label("Save document")
            .on_click(|_, _, _| println!("save"))
            .child("Save")
    }
}
```

An `ElementId` must remain stable within a view so GPUI can preserve focus and element state. `Button` handles pointer, Enter, and Space activation through one path and provides `disabled`, `selected`, `tab_index`, and `tab_stop` for semantic state and focus traversal.

### Controlled State

`Checkbox`, `Radio`, `Switch`, and `Toggle` are controlled components. Their callbacks report the next value; the application updates its own state and passes that value back on the next render:

```rust
use gpui_kit::prelude::*;
use gpui_kit::{Context, IntoElement, Render, Window};
use gpui_kit::base::{Checkbox, CheckboxIndicator};

struct Settings {
    telemetry: bool,
}

impl Render for Settings {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let checked = self.telemetry;
        let settings = cx.entity().downgrade();

        Checkbox::new("telemetry")
            .checked(checked)
            .accessibility_label("Send anonymous usage data")
            .on_change(move |state, _, cx| {
                _ = settings.update(cx, |this, cx| {
                    this.telemetry = state == gpui_kit::base::CheckboxState::Checked;
                    cx.notify();
                });
            })
            .child(
                CheckboxIndicator::new()
                    .checked(checked)
                    .child(if checked { "✓" } else { "" }),
            )
            .child("Send anonymous usage data")
    }
}
```

The caller also defines how semantic states look. For example:

```rust
Button::new("menu-trigger")
    .selected(menu_open)
    .disabled(is_busy)
    .styles(|styles| {
        styles
            .selected(|style| style.bg(rgb(0xe2e8f0)))
            .disabled(|style| style.opacity(0.5))
    })
    .child("Menu")
```

Semantic state styles express states such as checked, pressed, selected, indeterminate, and disabled. Every control resolves its final style in one fixed order:

1. the style applied directly in the main builder chain,
2. value states such as `checked`, `pressed`, `selected`, or `focused`,
3. `disabled`, which is always resolved last.

Semantic states therefore layer over the builder chain, the same way GPUI layers `hover`, `active`, and `focus_visible` on top of an element's base style. A state only overrides the fields it sets, so unrelated builder-chain styles are preserved. To keep a specific builder-chain style as the closest layer even while a state is active, replay it inside that state:

```rust
Button::new("save")
    .bg(brand)
    .styles(|styles| styles.disabled(|style| style.opacity(0.5).bg(brand)))
```

Base controls cannot suppress `hover` or `active` styles while disabled, because GPUI does not expose those refinements. Guard them at the call site with `when(!disabled, ..)`.

## Capability Overview

### Unstyled Controls

| API                                      | Behavior provided                                                                                     |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `Button`                                 | Click and keyboard activation, focus, disabled and selected states, and the Button accessibility role |
| `Checkbox` / `CheckboxIndicator`         | Checked, unchecked, and indeterminate states with corresponding accessibility semantics               |
| `Radio` / `RadioGroup`                   | Radio activation, focus, and a grouping container                                                     |
| `Switch` / `SwitchTrack` / `SwitchThumb` | A controlled switch with independently styled track and thumb parts                                   |
| `Toggle` / `ToggleGroup`                 | A controlled pressed state and grouping container                                                     |
| `Link`                                   | Link semantics and activation with an application-provided `open_with` navigation strategy            |
| `Table` and semantic table parts         | Table, row-group, row, column-header, cell roles, and accessibility indices without layout or styling |
| `Toast` / `ToastStack` / `ToastManager`  | Alert semantics, lifecycle, timers, limits, measured stack geometry, and interaction-aware motion     |

### Text Editing

Text editing is split into purpose-specific controls instead of exposing the
complete editor interface on every text field:

| Control                                                 | State           | Use                                                                                       |
| ------------------------------------------------------- | --------------- | ----------------------------------------------------------------------------------------- |
| [`Input`](../../website/base/primitives/input.md)       | `InputState`    | Single-line values, masking, validation, and number stepping                              |
| [`Textarea`](../../website/base/primitives/textarea.md) | `TextareaState` | Ordinary multi-line text, fixed rows, wrapping, and auto-grow                             |
| [`Editor`](../../website/base/primitives/editor.md)     | `EditorState`   | Source code, highlighting, gutter, folding, decorations, diagnostics, and LSP integration |

All three share the internal `InputBaseState` editing engine. Applications
should construct the purpose-specific state rather than configuring modes on
the shared engine.

The base layer never opens a URL by itself. This allows the same `Link` to target internal routing, an embedded web view, or the system browser.

### Focus and Interaction

- `FocusTrapElement` turns an interactive element into a focus trap. Tab and Shift-Tab cycle within the container.
- `active_focus_trap` returns the active focus trap for a window.
- `InteractiveElementExt` adds interaction helpers to GPUI interactive elements.
- `ElementExt` adds post-layout, prepaint observation to parent elements.
- `FocusableExt` draws a focus ring using the application theme.

### Scrolling and Large Data Sets

- `Scrollbar` supports `ScrollHandle`, `UniformListScrollHandle`, `ListState`, and `VirtualListScrollHandle`, with vertical, horizontal, and dual-axis modes.
- `ScrollbarMode` controls when a scrollbar is visible.
- `v_virtual_list` and `h_virtual_list` render only the visible range while allowing every item to have a different size.
- `VirtualListScrollHandle` reads or updates a virtual list's scroll position.
- `AutoScroll` provides timer-based edge scrolling during drag interactions.

A virtual list requires the caller to provide item sizes. Vertical lists use each item's height, while horizontal lists use each item's width. Unlike GPUI's `uniform_list`, this is suitable for data whose rows or columns do not share one size.

### Animation

`gpui-base` provides two animation APIs:

- `motion::transition` is the preferred value-transition API. The caller chooses the animated property; it supports duration, delay, custom easing, smooth target reversal, and reduced-motion preferences.
- `animation::Transition` is the legacy element-animation API for composing fade, slide, and size effects.

Foundation controls do not install animation automatically. Applications choose animation properties and timing according to their own visual language.

See the [Motion guide](../../website/base/motion.md) and run its five focused interactive demonstrations with:

```bash
cargo run -p gpui-base-examples --bin motion
```

### Themes and Styles

- `Theme` stores base-layer global configuration, including semantic tokens and scrollbar defaults.
- `SemanticThemeTokens` contains `colors`, `radius`, `spacing`, `typography`, and `shadow` scales.
- `StateStyle` is a semantic-state style builder compatible with fluent helpers such as `when` and `when_some`.
- `StyledExt` provides common helpers for horizontal and vertical flex layouts, margins and padding, font weights, focus styling, and debug outlines.
- `h_flex`, `v_flex`, and `box_shadow` are common element and style constructors.

The global base theme can be customized after initialization:

```rust
use gpui_kit::{px, rgb};
use gpui_kit::base::Theme;

let theme = Theme::global_mut(cx);
theme.tokens.colors.primary = rgb(0x2563eb).into();
theme.tokens.radius.md = px(8.);
```

Tokens describe design semantics; they do not automatically style unstyled controls. Applications read and apply these tokens in their own component implementations.

### General Data and Layout Utilities

| API                               | Purpose                                                                 |
| --------------------------------- | ----------------------------------------------------------------------- |
| `History`                         | Browser-style navigation trail with back and forward entries            |
| `UndoHistory`                     | Grouped undo and redo transactions                                      |
| `SliderState`                     | Single or range values, linear or logarithmic scales, and slider events |
| `IndexPath`                       | A section, row, and column index path                                   |
| `Placement` / `Side`              | Placement and layout direction descriptions                             |
| `AxisExt` / `LengthExt` / `Edges` | GPUI geometry extensions and serializable edges                         |

## Relationship to gpui-component

The crates target different abstraction levels and can be used in the same application:

|                      | `gpui-base`                                                      | `gpui-component`                                           |
| -------------------- | ---------------------------------------------------------------- | ---------------------------------------------------------- |
| Role                 | Behavior and infrastructure                                      | Complete UI component library                              |
| Default presentation | None                                                             | Included                                                   |
| Visual style owner   | Application                                                      | Component library, customizable through its Theme and APIs |
| Best suited for      | Custom design systems, registry components, and foundation reuse | Building complete desktop applications quickly             |
| Initialization       | `gpui_kit::base::init(cx)`                                       | `gpui_kit::init(cx)`, which includes base initialization   |

Do not migrate from `gpui-component` by mechanically replacing imports. For example, `gpui_kit::component::button::Button` is a fully styled higher-level component, while `gpui_kit::base::Button` requires the caller to provide its children and all presentation styles.

## Platform Support

Platform support follows GPUI and GPUI Component:

- macOS on Apple Silicon and Intel
- Linux on x86_64
- Windows on x86_64
- WebAssembly support depends on the APIs in use and the GPUI Web runtime

## Development and Verification

Run these commands from the GPUI Component repository root:

```bash
# Check the foundation crate
cargo check -p gpui-base

# Run the foundation crate tests
cargo test -p gpui-base

# Check formatting
cargo fmt --check

# Run Clippy
cargo clippy -p gpui-base -- --deny warnings
```

The current Rust interface is defined by the source code and generated API
documentation. See [`../../docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)
for the source-derived module architecture and
[`../../docs/STYLING-AND-MOTION.md`](../../docs/STYLING-AND-MOTION.md) for the
style and motion contracts.

## Related Resources

- [GPUI Kit repository](https://github.com/longbridge/gpui-kit)
- [GPUI Kit documentation](https://gpui-kit.com)
- [`gpui-component` crate](https://crates.io/crates/gpui-component)
- [`gpui-base` API documentation](https://docs.rs/gpui-base)
- GPUI
- [Contributing guide](../../CONTRIBUTING.md)

## License

Apache-2.0. See [`../../LICENSE-APACHE`](../../LICENSE-APACHE).
