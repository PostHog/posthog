<p align="center">
  <img src="https://raw.githubusercontent.com/longbridge/gpui-kit/main/website/public/logo.svg" width="112" alt="GPUI Kit logo" />
  <br>
  <strong>GPUI Kit</strong>
</p>

[English](./README.md) | [简体中文](./README.zh-CN.md)

[![Build Status](https://github.com/longbridge/gpui-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/longbridge/gpui-kit/actions/workflows/ci.yml) [![Docs](https://docs.rs/gpui-kit/badge.svg)](https://docs.rs/gpui-kit/) [![Crates.io](https://img.shields.io/crates/v/gpui-kit.svg)](https://crates.io/crates/gpui-kit)

Build fantastic, high-performance desktop apps with Rust and GPUI.

GPUI Kit is a comprehensive Rust desktop application framework. It combines a
production-ready UI system with application-grade data, layout, and editing
capabilities, all built on a reusable foundation of behavior, state, and
infrastructure. GPUI Kit ships 75+ documented components and primitives,
WebAssembly support, AccessKit accessibility, UI integration testing, and an
optional JavaScript extension runtime.

Documentation: <https://gpui-kit.com>

```text
gpui-kit             The one crate applications depend on
├── gpui-base        Unstyled behavior, state, and infrastructure
└── gpui-component   GPUI Component: the complete styled UI system
```

`gpui-kit` pins the matching GPUI release and re-exports GPUI, base, component,
and assets, so a Rust application lists a single dependency. JavaScript extension
hosts add `gpui-shell` separately; its default `components` feature supplies the styled catalog.

See the [executable application recipe and AI-assisted development acceptance checks](examples/ai_recipes/README.md) for a tested starting point and verification commands.

## Features

- **75+ Components and Primitives**: Forms, navigation, overlays, data display, editing, feedback, and layout, with polished interactions and productive defaults.
- **Production Ready**: Used to build Longbridge Pro from day one and continuously refined in a publicly shipped commercial desktop application.
- **WebAssembly**: Run applications and the same component showcases on the web with `wasm32-unknown-unknown`.
- **Accessibility**: AccessKit roles, names, states, relationships, and actions are built into the interaction layer and covered by tests.
- **UI Integration Testing**: Render real components in headless windows, drive pointer and keyboard input, and assert state, focus, layout, and accessibility.
- **Native Feel**: Modern controls inspired by macOS and Windows, backed by semantic themes and multiple sizes.
- **120 FPS**: GPU-accelerated interfaces that remain smooth under load.
- **Data Tables**: Virtual scrolling, fixed and resizable columns, sorting, and cell selection across hundreds of thousands of rows.
- **Virtual Lists**: Render only the visible range, including lists whose items have different sizes.
- **Code Editor**: Stable performance at 200K lines with Tree-sitter highlighting and LSP diagnostics, completion, and hover.
- **Dock Layout**: Resizable panels, draggable tabs, nested splits, and edge docks — all serializable.
- **Rich Content**: Native Markdown and HTML rendering, syntax highlighting, and built-in charts.
- **Design Freedom**: Use the complete visual system or build your own on the behavior and infrastructure in `gpui-base`.
- **JavaScript Extensions**: `gpui-shell` lets a shipped Rust host load panels and business logic as scripts, with every capability granted explicitly.
- **Cross Platform**: Ship one Rust codebase to macOS, Windows, and Linux.

## Framework Architecture

### Three layers. One ecosystem.

Use `gpui-component` to keep the application coherent with one complete visual
and interaction system. Use `gpui-base` when your product needs to create and
own that system itself. Use `gpui-shell` when the application should be
extensible in JavaScript after it ships.

| **`gpui-component`**             | **`gpui-base`**                               | **`gpui-shell`**                           |
| -------------------------------- | --------------------------------------------- | ------------------------------------------ |
| Complete, styled components      | Unstyled behavior and infrastructure          | JavaScript runtime hosted by Rust          |
| Productive defaults with theming | Full control over structure and visual design | Capabilities granted one at a time         |
| Best for building applications   | Best for building design systems              | Best for plugins and scripted applications |

```text
                             APPLICATION
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
              ▼                   ▼                   ▼
    ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
    │  gpui-component  │ │ Your Design      │ │    gpui-shell    │
    │    Styled UI     │ │ System           │ │  JS extensions   │
    └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘
             │                    │                    │
             └────────────────────┼────────────────────┘
                                  ▼
                        ┌──────────────────┐
                        │    gpui-base     │
                        │ Behavior · State │
                        │ Infrastructure   │
                        └────────┬─────────┘
                                 ▼
                               GPUI
```

> **Behavior belongs to the foundation. Presentation belongs to the application.**

Use **`gpui-component`** when you want polished controls ready to ship. Build on
**`gpui-base`** when your application should own its component source, layout,
styling, and motion while reusing difficult interaction behavior. Add
**`gpui-shell`** when contributors should extend the product without a fork or
a release.

The layering follows the same separation that makes the
[shadcn](https://ui.shadcn.com) ecosystem flexible:

| GPUI Kit ecosystem                   | Web ecosystem                   |
| ------------------------------------ | ------------------------------- |
| GPUI                                 | HTML + Tailwind CSS             |
| [`gpui-base`](crates/base/README.md) | [Base UI](https://base-ui.com)  |
| `gpui-component`                     | shadcn's styled component layer |

[Explore the architecture →](docs/ARCHITECTURE.md)

## Showcase

GPUI Kit has powered [Longbridge Pro](https://longbridge.com/desktop)
from day one. The framework is extracted from the demands of a publicly shipped
commercial desktop application rather than designed in isolation.

> **GPUI provides the rendering foundation. Longbridge provides the production foundation.**

<img width="1763" alt="Image" src="https://github.com/user-attachments/assets/e1ecb9c3-2dd3-431e-bd97-5a819c30e551" />

## Usage

```toml
[dependencies]
gpui-kit = "0.7"
```

`gpui-kit` always brings in GPUI and `gpui-base`; `gpui-component` and the
default icon set are on by default. Turn default
features off to keep only the layers you use. The `gpui-component` features (`inspector`, `decimal`,
`tree-sitter`, and each `tree-sitter-<language>`) are available under the same
names.

### GPUI Fast

Enable the optional `gpui-fast` feature to select [GPUI Fast](https://github.com/longbridge/gpui-fast)
for the core, native platforms, WebAssembly, and every enabled Kit layer:

```toml
[dependencies]
gpui-kit = { version = "0.7", features = ["gpui-fast"] }
```

Keep the same imports, initialization, and test macros; no application `[patch]`
or crate alias is needed. The default backend remains the pinned upstream GPUI
snapshot. Cargo features are additive, so upstream packages still compile when
Fast is selected. See [Getting Started](https://gpui-kit.com/docs/getting-started)
for feature combinations and comparison commands.

### Basic Example

```rs
use gpui_kit::component::button::*;
use gpui_kit::component::*;
use gpui_kit::*;

pub struct HelloWorld;
impl Render for HelloWorld {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        div()
            .v_flex()
            .gap_2()
            .size_full()
            .items_center()
            .justify_center()
            .child("Hello, World!")
            .child(
                Button::new("ok")
                    .primary()
                    .label("Let's Go!")
                    .on_click(|_, _, _| println!("Clicked!")),
            )
    }
}

fn main() {
    gpui_kit::application().run(move |cx| {
        // This must be called before using any GPUI Component features.
        gpui_kit::init(cx);

        gpui_kit::open_window(WindowOptions::default(), cx, |_, cx| {
            cx.new(|_| HelloWorld)
        })
        .expect("Failed to open window");
    });
}
```

`gpui_kit::open_window` is the application window entry point and always mounts a Base `Root`. Component initialization registers styled window facilities; Cargo features do not select a different root type.

### Icons

The default `assets` feature bundles the [Lucide](https://lucide.dev) icon set
as `gpui-kit-assets`; pass it to the application with
`gpui_kit::application().with_assets(gpui_kit::assets::Assets)`. To ship your
own icons instead, leave that feature out and name the SVG files as defined in
[IconName](https://github.com/longbridge/gpui-kit/blob/main/crates/component/src/icon.rs#L86).

## Skills for AI Coding Agents

Install the GPUI Kit skills for your AI coding agent (Cursor, Claude Code, Gemini CLI, Codex, etc.):

```bash
npx skills add longbridge/gpui-kit
```

| Skill                    | Description                                                                                                                         |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| `gpui-kit`               | Setup, component catalog, usage patterns, GPUI mechanics (elements, entities, async, focus, actions, tests), and the Coding Guides. |
| `gpui-kit-design-guides` | The Design Guides: layout, spacing, hierarchy, interaction states, overlays, and interface copy.                                    |

## Development

### Desktop Gallery (Story)

The `story` crate is a gallery application that showcases all available components. Run it with:

```bash
cargo run
```

### Examples

Some larger examples reuse the `story` gallery components and run as standalone packages:

```bash
# Dock layout system (panels, split views, tabs)
cargo run -p example-dock

# Markdown rendering
cargo run -p example-markdown

# HTML rendering
cargo run -p example-html
```

The `examples` directory also contains standalone examples, each focused on a single feature. Each example is a separate crate, run them with `cargo run -p <name>`:

```bash
# Code editor with LSP support and syntax highlighting
cargo run -p example-editor

# Basic hello world
cargo run -p hello_world

# System monitor (real-time charts with CPU/memory data)
cargo run -p system_monitor

# Window title customization
cargo run -p window_title
```

Check out [CONTRIBUTING.md](CONTRIBUTING.md) for more details.

## Compare to others

See the [comparison with Iced, egui and Qt 6](https://gpui-kit.com/docs/comparison) on the site.

## Related project: Native Shell

[Native Shell](https://nsh.dev) ([source](https://github.com/longbridge/native-shell)) is a sibling project that lets AI generate UI and renders it natively on iOS, Android, Linux (GTK) and macOS (AppKit). Its GPUI desktop backend is in development and will be built on GPUI Kit.

## License

Software source and documentation code examples: [Apache-2.0](LICENSE-APACHE).

Documentation prose and original illustrations in the Docs, Base, Component, and Shell sections (including Chinese translations) for which GPUI Kit holds licensing rights are also offered under [CC BY 4.0](LICENSE-DOCS.md). When copying or adapting that material, credit **GPUI Kit**, link to the source page and [CC BY 4.0 license](https://creativecommons.org/licenses/by/4.0/), and indicate changes. Existing Apache-2.0 permissions remain; earlier revisions retain their prior terms, and third-party contributions keep their own licenses unless separately authorized. Using facts or ideas without copying protected expression does not require attribution under CC BY 4.0.

- Built on [GPUI](https://github.com/zed-industries/zed), the UI framework from Zed Industries, also Apache-2.0. The `gpui-pre-*` crates are snapshots of it, published with Zed's license and notices intact.
- UI design based on [shadcn/ui](https://ui.shadcn.com), some from [Reui](https://reui.io).
- Icons from [Lucide](https://lucide.dev).
