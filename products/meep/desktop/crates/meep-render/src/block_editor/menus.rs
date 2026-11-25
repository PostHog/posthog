//! The editor's floating layers: the slash menu, the block menu behind the
//! drag handle, the link field and the format bar over selected text. They
//! are anchored to positions the document element painted last frame.
use super::model::*;
use super::*;
use gpui_kit::assets::IconName;
use gpui_kit::component::input::{Input, InputEvent, InputState};
use gpui_kit::component::{Icon, Sizable};
use gpui_kit::prelude::FluentBuilder;

actions!(block_editor_link, [CloseLink]);

pub(super) fn bind_keys(cx: &mut App) {
    cx.bind_keys([KeyBinding::new(
        "escape",
        CloseLink,
        Some("BlockEditorLink"),
    )]);
}

pub(crate) struct Item {
    pub kind: Kind,
    pub label: &'static str,
    pub hint: &'static str,
    pub icon: IconName,
    pub shortcut: &'static str,
    pub keys: &'static [&'static str],
}

pub(crate) const ITEMS: &[Item] = &[
    Item {
        kind: Kind::Paragraph,
        label: "Text",
        hint: "Just start writing with plain text.",
        icon: IconName::Type,
        shortcut: "",
        keys: &["text", "paragraph", "plain", "p"],
    },
    Item {
        kind: Kind::H1,
        label: "Heading 1",
        hint: "Big section heading.",
        icon: IconName::Heading1,
        shortcut: "#",
        keys: &["h1", "#", "title", "heading"],
    },
    Item {
        kind: Kind::H2,
        label: "Heading 2",
        hint: "Medium section heading.",
        icon: IconName::Heading2,
        shortcut: "##",
        keys: &["h2", "##", "subtitle", "heading"],
    },
    Item {
        kind: Kind::H3,
        label: "Heading 3",
        hint: "Small section heading.",
        icon: IconName::Heading3,
        shortcut: "###",
        keys: &["h3", "###", "heading"],
    },
    Item {
        kind: Kind::Bullet,
        label: "Bulleted list",
        hint: "Create a simple bulleted list.",
        icon: IconName::List,
        shortcut: "-",
        keys: &["bullet", "ul", "unordered", "list", "-"],
    },
    Item {
        kind: Kind::Numbered,
        label: "Numbered list",
        hint: "Create a list with numbering.",
        icon: IconName::ListOrdered,
        shortcut: "1.",
        keys: &["numbered", "ol", "ordered", "list", "1."],
    },
    Item {
        kind: Kind::Todo,
        label: "To-do list",
        hint: "Track tasks with a to-do list.",
        icon: IconName::SquareCheck,
        shortcut: "[]",
        keys: &["todo", "to-do", "task", "checkbox", "check", "[]"],
    },
    Item {
        kind: Kind::Quote,
        label: "Quote",
        hint: "Capture a quote.",
        icon: IconName::Quote,
        shortcut: "\"",
        keys: &["quote", "blockquote", "citation", "\""],
    },
    Item {
        kind: Kind::Code,
        label: "Code",
        hint: "Capture a code snippet.",
        icon: IconName::Code,
        shortcut: "```",
        keys: &["code", "snippet", "```", "pre"],
    },
    Item {
        kind: Kind::Divider,
        label: "Divider",
        hint: "Visually divide blocks.",
        icon: IconName::Minus,
        shortcut: "---",
        keys: &["divider", "hr", "line", "separator", "---"],
    },
];

pub(crate) fn label_of(kind: Kind) -> &'static str {
    ITEMS
        .iter()
        .find(|i| i.kind == kind)
        .map(|i| i.label)
        .unwrap_or("Text")
}

/// Items matching what was typed after `/`.
pub(crate) fn filter(query: &str) -> Vec<&'static Item> {
    let q = query.trim().to_lowercase();
    if q.is_empty() {
        return ITEMS.iter().collect();
    }
    let mut out: Vec<(u8, &'static Item)> = ITEMS
        .iter()
        .filter_map(|item| {
            let label = item.label.to_lowercase();
            let rank = if label.starts_with(&q) {
                0
            } else if label.split([' ', '-']).any(|w| w.starts_with(&q)) {
                1
            } else if item.keys.iter().any(|k| k.starts_with(&q)) {
                2
            } else if label.contains(&q) {
                3
            } else {
                return None;
            };
            Some((rank, item))
        })
        .collect();
    out.sort_by_key(|(rank, _)| *rank);
    out.into_iter().map(|(_, item)| item).collect()
}

/// The block menu's rows: actions, then the kinds to turn into.
#[derive(Clone, Copy, PartialEq)]
enum BlockAction {
    Delete,
    Duplicate,
    Turn(Kind),
}

fn block_actions() -> Vec<BlockAction> {
    let mut out = vec![BlockAction::Delete, BlockAction::Duplicate];
    out.extend(
        ITEMS
            .iter()
            .filter(|i| i.kind != Kind::Divider)
            .map(|i| BlockAction::Turn(i.kind)),
    );
    out
}

impl BlockEditor {
    /// What was typed after the slash, if the slash menu is open.
    pub(crate) fn slash_query(&self) -> Option<String> {
        let Some(Menu::Slash { block, offset, .. }) = &self.menu else {
            return None;
        };
        let text = &self.doc.block(*block).text;
        let end = self.sel.head.offset;
        text.get(offset + 1..end).map(str::to_owned)
    }

    /// Keeps the slash menu in step with the text: it closes when the caret
    /// leaves the query, the slash is deleted, or nothing matches a space.
    pub(crate) fn sync_slash(&mut self) {
        let Some(Menu::Slash {
            block,
            offset,
            selected,
        }) = &mut self.menu
        else {
            return;
        };
        let (block, offset) = (*block, *offset);
        let head = self.sel.head;
        let valid = self.sel.is_caret()
            && head.block == block
            && block < self.doc.len()
            && head.offset > offset
            && self.doc.block(block).text.get(offset..offset + 1) == Some("/");
        if !valid {
            self.menu = None;
            return;
        }
        let query = &self.doc.block(block).text[offset + 1..head.offset];
        let matches = filter(query);
        if query.contains('\n')
            || (matches.is_empty() && (query.ends_with(' ') || query.chars().count() > 12))
        {
            self.menu = None;
            return;
        }
        *selected = (*selected).min(matches.len().saturating_sub(1));
    }

    pub(crate) fn menu_close_slash(&mut self) {
        if matches!(
            self.menu,
            Some(Menu::Slash { .. }) | Some(Menu::Block { .. })
        ) {
            self.menu = None;
        }
    }

    /// Up and Down inside an open menu. Returns whether a menu took them.
    pub(crate) fn menu_navigate(&mut self, down: bool, cx: &mut Context<Self>) -> bool {
        let query = self.slash_query();
        match &mut self.menu {
            Some(Menu::Slash { selected, .. }) => {
                let n = filter(query.as_deref().unwrap_or("")).len();
                if n > 0 {
                    *selected = if down {
                        (*selected + 1) % n
                    } else {
                        (*selected + n - 1) % n
                    };
                    self.menu_scroll.scroll_to_item(*selected);
                }
                cx.notify();
                true
            }
            Some(Menu::Block { selected, .. }) => {
                let n = block_actions().len();
                *selected = if down {
                    (*selected + 1) % n
                } else {
                    (*selected + n - 1) % n
                };
                cx.notify();
                true
            }
            _ => false,
        }
    }

    /// Enter inside an open menu.
    pub(crate) fn menu_confirm(&mut self, window: &mut Window, cx: &mut Context<Self>) -> bool {
        match &self.menu {
            Some(Menu::Slash { selected, .. }) => {
                let selected = *selected;
                let items = filter(&self.slash_query().unwrap_or_default());
                match items.get(selected) {
                    Some(item) => self.pick_slash(item.kind, window, cx),
                    None => {
                        self.menu = None;
                        cx.notify();
                    }
                }
                true
            }
            Some(Menu::Block {
                selected, block, ..
            }) => {
                let (selected, block) = (*selected, *block);
                if let Some(action) = block_actions().get(selected).copied() {
                    self.run_block_action(block, action, window, cx);
                }
                true
            }
            _ => false,
        }
    }

    /// Applies a slash menu choice: the `/query` text goes, and the block
    /// turns into the kind (or a new block of that kind follows text).
    pub(crate) fn pick_slash(&mut self, kind: Kind, window: &mut Window, cx: &mut Context<Self>) {
        let Some(Menu::Slash { block, offset, .. }) = self.menu.take() else {
            return;
        };
        let end = self.sel.head.offset.max(offset + 1);
        self.transact(EditKind::Other, window, cx, |e, _, _| {
            e.doc.block_mut(block).replace(offset..end, "", &[]);
            let b = e.doc.block(block);
            let empty = b.is_empty();
            let target = if empty {
                block
            } else {
                // Text stays; the new kind starts a block after it.
                let at = e.doc.split(Pos::new(block, offset), Kind::Paragraph);
                at.block
            };
            let b = e.doc.block_mut(target);
            if kind == Kind::Divider {
                b.kind = Kind::Divider;
                b.text.clear();
                b.marks.clear();
                b.indent = 0;
                b.touch();
                let has_next = target + 1 < e.doc.len();
                if !has_next || e.doc.block(target + 1).kind == Kind::Divider {
                    e.doc
                        .blocks
                        .insert(target + 1, Rc::new(Block::new(Kind::Paragraph, "")));
                }
                e.sel = Selection::caret(Pos::new(target + 1, 0));
                return;
            }
            b.kind = kind;
            b.checked = false;
            if !kind.indents() {
                b.indent = 0;
            }
            if kind == Kind::Code {
                b.marks.clear();
            }
            b.touch();
            let len = b.len();
            e.sel = Selection::caret(Pos::new(target, if empty { 0 } else { len.min(offset) }));
            if !empty {
                e.sel = Selection::caret(Pos::new(target, 0));
            }
        });
        cx.notify();
    }

    fn run_block_action(
        &mut self,
        block: usize,
        action: BlockAction,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.menu = None;
        if !self.sel.blocks || !self.sel.block_span().contains(&block) {
            self.sel = Selection::block_range(block, block);
        }
        match action {
            BlockAction::Delete => {
                self.transact(EditKind::Other, window, cx, |e, _, _| {
                    e.delete_selection();
                });
            }
            BlockAction::Duplicate => self.duplicate(window, cx),
            BlockAction::Turn(kind) => {
                self.turn_into(kind, window, cx);
                let i = self.sel.head.block;
                let len = self.doc.block(i).len();
                self.set_selection(Selection::caret(Pos::new(i, len)), window, cx);
            }
        }
        self.focus.focus(window, cx);
        cx.notify();
    }

    /// ⌘K: the link field for the selected text.
    pub(crate) fn open_link(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.read_only {
            return;
        }
        let mut ranges = self.selected_ranges();
        let mut current = String::new();
        if ranges.is_empty() {
            let pos = self.sel.head;
            if let Some((r, url)) = self.doc.block(pos.block).link_at(pos.offset) {
                ranges = vec![(pos.block, r.clone())];
                current = url.to_string();
                self.sel =
                    Selection::range(Pos::new(pos.block, r.start), Pos::new(pos.block, r.end));
            }
        } else if let Some((i, r)) = ranges.first()
            && let Some((_, url)) = self.doc.block(*i).link_at(r.start)
        {
            current = url.to_string();
        }
        let input = cx.new(|cx| {
            let mut state = InputState::new(window, cx).placeholder("Paste or type a link");
            state.set_value(current, window, cx);
            state
        });
        let subscription = cx.subscribe_in(
            &input,
            window,
            |this, input, event: &InputEvent, window, cx| {
                if let InputEvent::PressEnter { .. } = event {
                    let url = input.read(cx).value().to_string();
                    if let Some(Menu::Link { ranges, .. }) = this.menu.take() {
                        this.apply_link(ranges, &url, window, cx);
                    }
                    this.focus.focus(window, cx);
                    cx.notify();
                }
            },
        );
        input.update(cx, |s, cx| s.focus(window, cx));
        self.menu = Some(Menu::Link {
            input,
            ranges,
            _subscription: subscription,
        });
        cx.notify();
    }

    fn close_link(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.menu = None;
        self.focus.focus(window, cx);
        cx.notify();
    }

    /// Where a position is in window coordinates (its row's top-left and
    /// height), from the last layout.
    fn window_point(&self, pos: Pos) -> Option<(Point<Pixels>, Pixels)> {
        let r = self.caret_rect(pos, false)?;
        let l = self.geo.layouts.get(pos.block)?;
        let top = r.origin.y - (l.line_height - r.size.height) / 2.;
        Some((self.bounds.origin + point(r.origin.x, top), l.line_height))
    }

    fn show_format_bar(&self) -> bool {
        self.focused
            && !self.read_only
            && !self.sel.blocks
            && !self.sel.is_caret()
            && self.gesture.is_none()
            && self.menu.is_none()
            && self.marked.is_none()
            && !self.selected_ranges().is_empty()
    }

    pub(crate) fn render_overlays(
        &mut self,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Option<AnyElement> {
        let colors = self.colors;
        let viewport = window.viewport_size().height;
        if self.show_format_bar() {
            let (at, h) = self.window_point(self.sel.start())?;
            // Above the selection, or below it when the window's top is near.
            let place = if at.y - px(52.) >= px(8.) {
                (at - point(px(0.), px(8.)), Anchor::BottomLeft)
            } else {
                (point(at.x, at.y + h + px(8.)), Anchor::TopLeft)
            };
            return Some(self.format_bar(place, colors, cx));
        }
        match &self.menu {
            Some(Menu::Slash {
                block,
                offset,
                selected,
            }) => {
                let (at, h) = self.window_point(Pos::new(*block, *offset))?;
                let query = self.slash_query().unwrap_or_default();
                let rows = filter(&query).len().max(1) as f32;
                let height = px(42. + (rows * 46.).min(330.));
                let place = place_beside(at.x - px(2.), at.y, at.y + h, height, viewport);
                Some(self.slash_menu(place, &query, *selected, colors, cx))
            }
            Some(Menu::Block {
                block, selected, ..
            }) => {
                let (_, handle) = self.gutter_rects((*block).min(self.doc.len() - 1));
                let r = handle + self.bounds.origin;
                let place = place_beside(r.left(), r.top(), r.bottom(), px(372.), viewport);
                Some(self.block_menu(place, *block, *selected, colors, cx))
            }
            Some(Menu::Link { input, ranges, .. }) => {
                let pos = ranges
                    .first()
                    .map(|(i, r)| Pos::new(*i, r.start))
                    .unwrap_or(self.sel.head);
                let (at, h) = self.window_point(pos)?;
                let place = place_beside(at.x, at.y, at.y + h, px(52.), viewport);
                Some(self.link_field(place, input.clone(), colors, cx))
            }
            None => None,
        }
    }

    fn surface(colors: Colors) -> Div {
        div()
            .bg(colors.canvas)
            .border_1()
            .border_color(colors.ink_alpha(if colors.dark { 0.16 } else { 0.1 }))
            .rounded(px(8.))
            .shadow(vec![
                BoxShadow {
                    color: hsla(0., 0., 0., if colors.dark { 0.4 } else { 0.08 }),
                    offset: point(px(0.), px(8.)),
                    blur_radius: px(24.),
                    spread_radius: px(0.),
                    inset: false,
                },
                BoxShadow {
                    color: hsla(0., 0., 0., if colors.dark { 0.3 } else { 0.06 }),
                    offset: point(px(0.), px(2.)),
                    blur_radius: px(6.),
                    spread_radius: px(0.),
                    inset: false,
                },
            ])
            .occlude()
    }

    fn slash_menu(
        &self,
        at: (Point<Pixels>, Anchor),
        query: &str,
        selected: usize,
        colors: Colors,
        cx: &mut Context<Self>,
    ) -> AnyElement {
        let items = filter(query);
        let rows: Vec<AnyElement> = items
            .iter()
            .enumerate()
            .map(|(i, item)| {
                let kind = item.kind;
                let active = i == selected;
                div()
                    .id(ElementId::Name(format!("slash-{}", item.label).into()))
                    .flex()
                    .items_center()
                    .gap(px(10.))
                    .h(px(46.))
                    .mx(px(4.))
                    .px(px(6.))
                    .rounded(px(6.))
                    .when(active, |el| el.bg(colors.hover()))
                    .on_mouse_move(cx.listener(move |this, _: &MouseMoveEvent, _, cx| {
                        if let Some(Menu::Slash { selected, .. }) = &mut this.menu
                            && *selected != i
                        {
                            *selected = i;
                            cx.notify();
                        }
                    }))
                    .on_mouse_down(
                        MouseButton::Left,
                        cx.listener(move |this, _, window, cx| {
                            cx.stop_propagation();
                            this.pick_slash(kind, window, cx);
                        }),
                    )
                    .child(
                        div()
                            .size(px(34.))
                            .flex_shrink_0()
                            .flex()
                            .items_center()
                            .justify_center()
                            .rounded(px(6.))
                            .border_1()
                            .border_color(colors.ink_alpha(0.1))
                            .bg(colors.canvas)
                            .child(
                                Icon::new(item.icon)
                                    .size(px(17.))
                                    .text_color(colors.ink_alpha(0.7)),
                            ),
                    )
                    .child(
                        div()
                            .flex_1()
                            .min_w_0()
                            .flex()
                            .flex_col()
                            .child(
                                div()
                                    .text_size(px(14.))
                                    .text_color(colors.ink)
                                    .child(item.label),
                            )
                            .child(
                                div()
                                    .text_size(px(12.))
                                    .text_color(colors.ink_alpha(0.5))
                                    .truncate()
                                    .child(item.hint),
                            ),
                    )
                    .when(!item.shortcut.is_empty(), |el| {
                        el.child(
                            div()
                                .text_size(px(12.))
                                .text_color(colors.ink_alpha(0.35))
                                .child(item.shortcut),
                        )
                    })
                    .into_any_element()
            })
            .collect();
        let empty = items.is_empty();
        deferred(
            anchored()
                .position(at.0)
                .anchor(at.1)
                .snap_to_window_with_margin(px(8.))
                .child(
                    Self::surface(colors)
                        .id("slash-menu")
                        .w(px(320.))
                        .py(px(6.))
                        .child(
                            div()
                                .px(px(14.))
                                .pt(px(4.))
                                .pb(px(6.))
                                .text_size(px(11.5))
                                .font_weight(FontWeight::MEDIUM)
                                .text_color(colors.ink_alpha(0.5))
                                .child(if empty { "No results" } else { "Basic blocks" }),
                        )
                        .child(
                            div()
                                .id("slash-items")
                                .max_h(px(330.))
                                .overflow_y_scroll()
                                .track_scroll(&self.menu_scroll)
                                .flex()
                                .flex_col()
                                .children(rows),
                        ),
                ),
        )
        .with_priority(3)
        .into_any_element()
    }

    fn block_menu(
        &self,
        at: (Point<Pixels>, Anchor),
        block: usize,
        selected: usize,
        colors: Colors,
        cx: &mut Context<Self>,
    ) -> AnyElement {
        let current = self.doc.block(block.min(self.doc.len() - 1)).kind;
        let mut rows: Vec<AnyElement> = Vec::new();
        for (i, action) in block_actions().into_iter().enumerate() {
            if i == 2 {
                rows.push(
                    div()
                        .h(px(1.))
                        .my(px(5.))
                        .mx(px(10.))
                        .bg(colors.ink_alpha(0.08))
                        .into_any_element(),
                );
                rows.push(
                    div()
                        .px(px(14.))
                        .pt(px(2.))
                        .pb(px(4.))
                        .text_size(px(11.5))
                        .font_weight(FontWeight::MEDIUM)
                        .text_color(colors.ink_alpha(0.5))
                        .child("Turn into")
                        .into_any_element(),
                );
            }
            let (icon, label, hint, checked) = match action {
                BlockAction::Delete => (IconName::Trash, "Delete", "Del", false),
                BlockAction::Duplicate => (IconName::Copy, "Duplicate", "⌘D", false),
                BlockAction::Turn(kind) => {
                    let item = ITEMS.iter().find(|it| it.kind == kind).unwrap();
                    (item.icon, item.label, "", kind == current)
                }
            };
            let active = i == selected;
            rows.push(
                div()
                    .id(ElementId::Name(format!("block-menu-{label}").into()))
                    .flex()
                    .items_center()
                    .gap(px(8.))
                    .h(px(28.))
                    .mx(px(4.))
                    .px(px(8.))
                    .rounded(px(6.))
                    .text_size(px(13.5))
                    .text_color(colors.ink)
                    .when(active, |el| el.bg(colors.hover()))
                    .on_mouse_move(cx.listener(move |this, _: &MouseMoveEvent, _, cx| {
                        if let Some(Menu::Block { selected, .. }) = &mut this.menu
                            && *selected != i
                        {
                            *selected = i;
                            cx.notify();
                        }
                    }))
                    .on_mouse_down(
                        MouseButton::Left,
                        cx.listener(move |this, _, window, cx| {
                            cx.stop_propagation();
                            this.run_block_action(block, action, window, cx);
                        }),
                    )
                    .child(
                        Icon::new(icon)
                            .size(px(16.))
                            .text_color(colors.ink_alpha(0.65)),
                    )
                    .child(div().flex_1().child(label))
                    .when(!hint.is_empty(), |el| {
                        el.child(
                            div()
                                .text_size(px(12.))
                                .text_color(colors.ink_alpha(0.4))
                                .child(hint),
                        )
                    })
                    .when(checked, |el| {
                        el.child(
                            Icon::new(IconName::Check)
                                .size(px(14.))
                                .text_color(colors.ink_alpha(0.65)),
                        )
                    })
                    .into_any_element(),
            );
        }
        deferred(
            anchored()
                .position(at.0)
                .anchor(at.1)
                .snap_to_window_with_margin(px(8.))
                .child(
                    Self::surface(colors)
                        .id("block-menu")
                        .w(px(240.))
                        .py(px(6.))
                        .flex()
                        .flex_col()
                        .children(rows),
                ),
        )
        .with_priority(3)
        .into_any_element()
    }

    fn link_field(
        &self,
        at: (Point<Pixels>, Anchor),
        input: Entity<InputState>,
        colors: Colors,
        cx: &mut Context<Self>,
    ) -> AnyElement {
        deferred(
            anchored()
                .position(at.0)
                .anchor(at.1)
                .snap_to_window_with_margin(px(8.))
                .child(
                    Self::surface(colors)
                        .id("link-field")
                        .key_context("BlockEditorLink")
                        .on_action(cx.listener(|this, _: &CloseLink, window, cx| {
                            this.close_link(window, cx)
                        }))
                        .w(px(340.))
                        .p(px(8.))
                        .flex()
                        .items_center()
                        .gap(px(6.))
                        .child(
                            Icon::new(IconName::Link)
                                .size(px(15.))
                                .text_color(colors.ink_alpha(0.5)),
                        )
                        .child(
                            div()
                                .flex_1()
                                .child(Input::new(&input).small().appearance(false)),
                        ),
                ),
        )
        .with_priority(3)
        .into_any_element()
    }

    fn format_bar(
        &self,
        at: (Point<Pixels>, Anchor),
        colors: Colors,
        cx: &mut Context<Self>,
    ) -> AnyElement {
        let button = |id: &'static str,
                      active: bool,
                      content: AnyElement,
                      cx: &mut Context<Self>,
                      run: fn(&mut Self, &mut Window, &mut Context<Self>)| {
            div()
                .id(id)
                .size(px(28.))
                .flex()
                .items_center()
                .justify_center()
                .rounded(px(5.))
                .text_size(px(14.))
                .text_color(if active {
                    colors.accent
                } else {
                    colors.ink_alpha(0.8)
                })
                .hover(|s| s.bg(colors.hover()))
                .on_mouse_down(
                    MouseButton::Left,
                    cx.listener(move |this, _, window, cx| {
                        cx.stop_propagation();
                        run(this, window, cx);
                    }),
                )
                .child(content)
                .into_any_element()
        };
        let kind = self.doc.block(self.sel.start().block).kind;
        let bold = self.style_active(&Style::Bold);
        let italic = self.style_active(&Style::Italic);
        let strike = self.style_active(&Style::Strike);
        let code = self.style_active(&Style::Code);
        let link = self.style_active(&Style::Link("".into()));
        let ink = colors.ink_alpha(0.8);
        let buttons = vec![
            div()
                .px(px(8.))
                .h(px(28.))
                .flex()
                .items_center()
                .text_size(px(13.))
                .text_color(colors.ink_alpha(0.65))
                .child(super::menus::label_of(kind))
                .into_any_element(),
            div()
                .w(px(1.))
                .h(px(18.))
                .mx(px(2.))
                .bg(colors.ink_alpha(0.1))
                .into_any_element(),
            button(
                "fmt-bold",
                bold,
                Icon::new(IconName::Bold)
                    .size(px(15.))
                    .text_color(if bold { colors.accent } else { ink })
                    .into_any_element(),
                cx,
                |e, w, cx| e.toggle_style(Style::Bold, w, cx),
            ),
            button(
                "fmt-italic",
                italic,
                Icon::new(IconName::Italic)
                    .size(px(15.))
                    .text_color(if italic { colors.accent } else { ink })
                    .into_any_element(),
                cx,
                |e, w, cx| e.toggle_style(Style::Italic, w, cx),
            ),
            button(
                "fmt-strike",
                strike,
                Icon::new(IconName::Strikethrough)
                    .size(px(15.))
                    .text_color(if strike { colors.accent } else { ink })
                    .into_any_element(),
                cx,
                |e, w, cx| e.toggle_style(Style::Strike, w, cx),
            ),
            button(
                "fmt-code",
                code,
                Icon::new(IconName::Code)
                    .size(px(15.))
                    .text_color(if code { colors.accent } else { ink })
                    .into_any_element(),
                cx,
                |e, w, cx| e.toggle_style(Style::Code, w, cx),
            ),
            button(
                "fmt-link",
                link,
                Icon::new(IconName::Link)
                    .size(px(15.))
                    .text_color(if link { colors.accent } else { ink })
                    .into_any_element(),
                cx,
                |e, w, cx| e.open_link(w, cx),
            ),
        ];
        deferred(
            anchored()
                .position(at.0)
                .anchor(at.1)
                .snap_to_window_with_margin(px(8.))
                .child(
                    Self::surface(colors)
                        .id("format-bar")
                        .flex()
                        .items_center()
                        .gap(px(1.))
                        .p(px(3.))
                        .children(buttons),
                ),
        )
        .with_priority(3)
        .into_any_element()
    }
}

/// Below a line when the menu fits there, otherwise above it.
fn place_beside(
    x: Pixels,
    top: Pixels,
    bottom: Pixels,
    height: Pixels,
    viewport: Pixels,
) -> (Point<Pixels>, Anchor) {
    let gap = px(6.);
    if bottom + gap + height <= viewport - px(8.) || top - gap - height < px(8.) {
        (point(x, bottom + gap), Anchor::TopLeft)
    } else {
        (point(x, top - gap), Anchor::BottomLeft)
    }
}
