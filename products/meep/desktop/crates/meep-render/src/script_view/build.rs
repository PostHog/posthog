//! Builds GPUI elements from a script's element tree: containers, text,
//! controls and the element-specific arms. `components`, `interact`,
//! `table` and `scene_view` add the larger families.
use super::*;

#[derive(Clone)]
pub(super) struct Build {
    pub(super) read_only: bool,
    /// The node a region view renders: built here, never embedded again,
    /// and filling the bounds its parent laid the region out at.
    pub(super) region_root: Option<Rc<Node>>,
    /// The region building, which owns the regions it embeds.
    pub(super) region_key: Option<Rc<str>>,
    /// Prefix for this view's motion state, so two views never share a channel.
    pub(super) scope: Rc<str>,
    pub(super) shared: Rc<Shared>,
    pub(super) weak: WeakEntity<ScriptView>,
    pub(super) inputs: Rc<HashMap<String, Editor>>,
    /// Building inside a control (a clickable or draggable element, a
    /// popover trigger, a table), where text is not selectable by default.
    pub(super) control: bool,
}
impl Build {
    pub(super) fn send(&self, handler: u32, argument: Value) -> impl Fn(&mut App) + 'static {
        let weak = self.weak.clone();
        move |cx| {
            let _ = weak.update(cx, |view, cx| {
                view.invoke(handler, argument.clone(), true, cx)
            });
        }
    }
    pub(super) fn dispatch(
        &self,
        handler: u32,
    ) -> impl Fn(&ClickEvent, &mut Window, &mut App) + 'static {
        let send = self.send(handler, Value::Null);
        move |_, _, cx| send(cx)
    }
    pub(super) fn children(
        &self,
        node: &Rc<Node>,
        window: &mut Window,
        cx: &mut App,
    ) -> Vec<AnyElement> {
        node.children
            .iter()
            .map(|child| self.node(child, window, cx))
            .collect()
    }
    pub(super) fn container(
        &self,
        base: Div,
        node: &Rc<Node>,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let p = &node.p;
        // Styled first: it takes this element's motion frame, which building
        // a child resets. A control's children are its label, not
        // selectable by default.
        let el = style(base, node);
        let el = el.children(self.within(p).children(node, window, cx));
        if interact::interactive(p) {
            return self.interact(el, node, window, cx);
        }
        match color(&p["hoverBg"]) {
            Some(c) => el.hover(move |s| s.bg(c)).into_any_element(),
            None => el.into_any_element(),
        }
    }
    /// Elements that contain children. Kept small: this recursion runs once
    /// per tree level, and a large frame here multiplies by the tree depth.
    pub(super) fn node(&self, node: &Rc<Node>, window: &mut Window, cx: &mut App) -> AnyElement {
        if let Some(region) = regions::embed(self, node, window, cx) {
            return region;
        }
        // Built by the view's root instead (see `layers`).
        if node.view_layer {
            return div().into_any_element();
        }
        self.layer(node, window, cx)
    }
    /// An element, painted above the rest of the view when it is a layer.
    pub(super) fn layer(&self, node: &Rc<Node>, window: &mut Window, cx: &mut App) -> AnyElement {
        let p = &node.p;
        let element = self.moving(node, window, cx);
        // Layers paint above the rest of the view, in at most three levels.
        match p["layer"].as_u64() {
            Some(layer) => deferred(ViewClipped {
                child: element,
                shared: self.shared.clone(),
            })
            .with_priority(layer.clamp(1, 3) as usize)
            .into_any_element(),
            None => element,
        }
    }
    pub(super) fn moving(&self, node: &Rc<Node>, window: &mut Window, cx: &mut App) -> AnyElement {
        let p = &node.p;
        // A parent that never styles itself must not pass its frame down.
        MOTION.with(|m| m.set(None));
        let settling = self.shared.settling(node, window, cx);
        let moved = |frame| match settling {
            Some((dx, dy)) => Some(crate::script_motion::Frame::moved(frame, dx, dy)),
            None => frame,
        };
        if !crate::script_motion::declared(p) {
            if settling.is_none() {
                return self.element(node, window, cx);
            }
            MOTION.with(|m| m.set(moved(None)));
        } else {
            match crate::script_motion::sample(&self.scope, &node.key, p, &color, window, cx) {
                crate::script_motion::Sampled::Gone => {
                    self.shared.settle.borrow_mut().remove(&*node.key);
                    return div().into_any_element();
                }
                crate::script_motion::Sampled::Frame(frame) => MOTION.with(|m| m.set(moved(frame))),
            }
        }
        let element = self.element(node, window, cx);
        // Elements without style props ignore motion rather than carry it
        // into the next element built.
        MOTION.with(|m| m.set(None));
        element
    }
    /// Elements that contain children. Kept small: this recursion runs once
    /// per tree level, and a large frame here multiplies by the tree depth.
    #[inline(never)]
    pub(super) fn element(&self, node: &Rc<Node>, window: &mut Window, cx: &mut App) -> AnyElement {
        let p = &node.p;
        let key = &node.key;
        let id = ElementId::Name(key.clone());
        match node.kind {
            "reveal" => {
                let id = ElementId::Name(format!("{}:{key}:reveal", self.scope).into());
                let progress = ui::motion::reveal(id.clone(), p["open"] == true, window, cx);
                if progress <= 0. {
                    return div().into_any_element();
                }
                gpui_kit::base::MotionReveal::new(
                    id,
                    progress,
                    self.container(ui::column(), node, window, cx),
                )
                .into_any_element()
            }
            kind @ ("page" | "column" | "row" | "box" | "reading" | "card") => {
                let base = container_base(kind).unwrap_or_else(div);
                self.container(base, node, window, cx)
            }
            // Reading text joins the window's text selection unless it is a
            // control's (see `selectable`).
            "text" | "caption" | "mono" | "heading" if self.selects(p) => {
                let (base, role) = match node.kind {
                    "caption" => (ui::caption_style(), Role::Label),
                    "mono" => (ui::mono_style(), Role::Label),
                    "heading" => (ui::heading_style(), Role::Heading),
                    _ => (div(), Role::Label),
                };
                self.selectable_text(node, base, role, window, cx)
            }
            "text" => self.container(div().child(text(p, "text")), node, window, cx),
            "caption" => self.container(ui::caption(text(p, "text")), node, window, cx),
            "mono" => self.container(ui::mono(text(p, "text")), node, window, cx),
            "label" => self.container(ui::section_label(text(p, "text")), node, window, cx),
            "scroll" => {
                let mut el = style(container_base("scroll").unwrap_or_else(div), node);
                // A cached region's root fills the bounds its view was given.
                if self
                    .region_root
                    .as_ref()
                    .is_some_and(|root| Rc::ptr_eq(root, node))
                {
                    el = el.size_full();
                }
                let el = el
                    .children(self.children(node, window, cx))
                    .id(id)
                    .overflow_y_scroll();
                self.scroll_events(el, node).into_any_element()
            }
            "form" => style(ui::forms::form(id), node)
                .children(self.children(node, window, cx))
                .into_any_element(),
            "field" => {
                let control = self
                    .children(node, window, cx)
                    .into_iter()
                    .next()
                    .unwrap_or_else(|| div().into_any_element());
                let mut field = ui::forms::Field::new(id, text(p, "label"), control);
                if p["optional"] == true {
                    field = field.optional();
                }
                if let Some(hint) = p["hint"].as_str() {
                    field = field.hint(hint.to_owned());
                }
                if let Some(error) = p["error"].as_str().filter(|e| !e.is_empty()) {
                    field = field.error(error.to_owned());
                }
                if let Some(editor) = p["for"].as_str().and_then(|target| self.inputs.get(target)) {
                    let handle = match editor {
                        Editor::Line(state) => state.read(cx).focus_handle(cx),
                        Editor::Area(state) => state.read(cx).focus_handle(cx),
                        Editor::Date(state, _) => state.read(cx).focus_handle(cx),
                        Editor::Time(state) => state.read(cx).focus_handle(cx),
                        Editor::Blocks(state) => state.read(cx).focus_handle(),
                    };
                    field = field.focus(&handle);
                }
                field.into_any_element()
            }
            "actions" => ui::forms::actions(
                text(p, "status"),
                ui::row()
                    .gap(px(8.))
                    .children(self.children(node, window, cx)),
            )
            .into_any_element(),
            "header" => ui::page_header(
                id,
                text(p, "title"),
                text(p, "subtitle"),
                ui::row()
                    .gap(px(4.))
                    .children(self.children(node, window, cx)),
            )
            .into_any_element(),
            _ => self.leaf(node, window, cx),
        }
    }
    #[inline(never)]
    pub(super) fn leaf(&self, node: &Rc<Node>, window: &mut Window, cx: &mut App) -> AnyElement {
        let p = &node.p;
        let key = &node.key;
        let id = ElementId::Name(key.clone());
        match node.kind {
            "list_row" => {
                let title = text(p, "title");
                let mut row = style(ui::list_row(id, title.clone(), text(p, "subtitle")), node)
                    .tooltip(move |window, cx| {
                        gpui_kit::component::tooltip::Tooltip::new(title.clone()).build(window, cx)
                    });
                if p["selected"] == true {
                    row = row.bg(rgb(crate::sdk::ui::theme::color(ui::INSET)));
                }
                if let Some(h) = handler(p, "onClick") {
                    row = row
                        .cursor_pointer()
                        .hover(|s| s.bg(rgb(crate::sdk::ui::theme::color(ui::INSET))))
                        .on_click(self.dispatch(h));
                }
                row.into_any_element()
            }
            "section" => ui::forms::section(text(p, "title"), text(p, "detail")).into_any_element(),
            "heading" => style(ui::heading(id, text(p, "text")), node).into_any_element(),
            "badge" => style(
                div()
                    .flex_shrink_0()
                    .px(px(6.))
                    .rounded(px(4.))
                    .bg(rgb(crate::sdk::ui::theme::color(ui::INSET)))
                    .text_size(px(ui::SMALL))
                    .text_color(rgb(crate::sdk::ui::theme::color(ui::SECONDARY)))
                    .child(text(p, "text")),
                node,
            )
            .into_any_element(),
            "link" => {
                let url = p["url"].as_str().map(str::to_owned);
                let click = handler(p, "onClick").map(|h| self.send(h, Value::Null));
                style(
                    div()
                        .id(id)
                        .text_color(rgb(ui::theme::get(10)))
                        .cursor_pointer()
                        .hover(|s| s.underline())
                        .child(text(p, "text")),
                    node,
                )
                .on_click(move |_, _, cx| {
                    if let Some(click) = &click {
                        click(cx);
                    } else if let Some(url) = &url
                        && crate::links::web_url(url).is_ok()
                    {
                        cx.open_url(url);
                    }
                })
                .into_any_element()
            }
            "read_only" => {
                ui::forms::read_only(id, text(p, "label"), text(p, "value")).into_any_element()
            }
            "logo" => style(
                crate::brands::logo(
                    &text(p, "service"),
                    p["size"].as_f64().unwrap_or(16.) as f32,
                )
                .id(id)
                .aria_label(text(p, "service")),
                node,
            )
            .into_any_element(),
            "icon" => {
                let mut icon = Icon::new(icon_name(&text(p, "name")))
                    .size(number(p, "size").unwrap_or(px(14.)));
                if let Some(c) = color(&p["color"]) {
                    icon = icon.text_color(c);
                }
                // Icons are vector marks, so they also take scale and rotation.
                if let Some(frame) = MOTION.with(|m| m.take()) {
                    if let Some(t) = frame.transformation() {
                        icon = icon.transform(t);
                    }
                    icon = frame.apply(icon, p);
                }
                icon.into_any_element()
            }
            "button" => {
                let label = text(p, "label");
                let mut button = match p["variant"].as_str() {
                    Some("primary") => {
                        ui::primary_button_state(id, label, self.read_only || p["disabled"] == true)
                    }
                    Some("secondary") => ui::forms::secondary_button(id, label),
                    _ => ui::button(id, label),
                };
                if let Some(icon) = p["icon"].as_str() {
                    button = button.icon(icon_name(icon));
                }
                button = button.disabled(self.read_only || p["disabled"] == true);
                if let Some(h) = handler(p, "onClick") {
                    button = button.on_click(self.dispatch(h));
                }
                style(button, node).into_any_element()
            }
            "icon_button" => {
                let disabled = self.read_only || p["disabled"] == true;
                let mut button = ui::icon_button(id, icon_name(&text(p, "icon")), text(p, "label"))
                    .disabled(disabled);
                if p["variant"] == "primary" {
                    // The one action a surface exists for (Send): a filled circle.
                    let (fill, ink) = if disabled {
                        (crate::sdk::ui::ink(0x12), rgb(ui::theme::get(2)).into())
                    } else {
                        (rgb(ui::theme::get(10)), rgb(ui::theme::get(13)).into())
                    };
                    let ink: Hsla = ink;
                    button = button.size(px(28.)).rounded_full().bg(fill).text_color(ink);
                }
                if let Some(h) = handler(p, "onClick") {
                    button = button.on_click(self.dispatch(h));
                }
                button.into_any_element()
            }
            "input" | "textarea" => match self.inputs.get(key.as_ref()) {
                Some(Editor::Line(state)) => {
                    let label = p["label"]
                        .as_str()
                        .or(p["placeholder"].as_str())
                        .unwrap_or("Text");
                    let mut input = ui::forms::input(state, label.to_owned());
                    if p["invalid"] == true {
                        input = input.border_color(rgb(ui::forms::INVALID));
                    }
                    style(input.disabled(self.read_only), node).into_any_element()
                }
                Some(Editor::Area(state)) => {
                    let label = p["label"]
                        .as_str()
                        .or(p["placeholder"].as_str())
                        .unwrap_or("Text");
                    let rows = p["rows"].as_f64().unwrap_or(4.) as f32;
                    let height = p["h"]
                        .as_f64()
                        .map(|h| h as f32)
                        .unwrap_or(rows * 20. + 16.);
                    let mut editor = ui::forms::textarea(state, label.to_owned(), height)
                        .disabled(self.read_only || p["disabled"] == true);
                    if p["bare"] == true {
                        // Inside a surface that draws its own edge (a composer).
                        editor = editor.appearance(false).px(px(4.)).py(px(4.));
                    }
                    if p["submitOnEnter"] == true {
                        // The input emits PressEnter and propagates submit. Consume
                        // it here so a parent/default handler cannot insert a newline.
                        div()
                            .w_full()
                            .flex_shrink_0()
                            .child(editor)
                            .on_action(|_: &gpui_kit::component::input::Enter, _, cx| {
                                cx.stop_propagation()
                            })
                            .into_any_element()
                    } else {
                        editor.into_any_element()
                    }
                }
                _ => {
                    ui::caption("Text fields are not available inside list rows").into_any_element()
                }
            },
            #[cfg(not(target_family = "wasm"))]
            "workflow_editor" => self.workflow_editor(node, window, cx),
            #[cfg(target_family = "wasm")]
            "workflow_editor" => {
                ui::caption("Workflow editing requires a native host.").into_any_element()
            }
            "workflow_outline" => self.workflow_outline(node, window, cx),
            "block_editor" => self.block_editor(node),
            "checkbox" => {
                let mut checkbox = Checkbox::new(id)
                    .checked(p["checked"] == true)
                    .label(text(p, "label"))
                    .disabled(self.read_only || p["disabled"] == true);
                if let Some(h) = handler(p, "onChange") {
                    let weak = self.weak.clone();
                    checkbox = checkbox.on_click(move |checked, _, cx| {
                        let _ =
                            weak.update(cx, |view, cx| view.invoke(h, json!(*checked), true, cx));
                    });
                }
                checkbox.into_any_element()
            }
            "toggle" => {
                let mut toggle = Switch::new(id)
                    .checked(p["checked"] == true)
                    .label(text(p, "label"))
                    .disabled(self.read_only || p["disabled"] == true);
                if let Some(h) = handler(p, "onChange") {
                    let weak = self.weak.clone();
                    toggle = toggle.on_click(move |checked, _, cx| {
                        let _ =
                            weak.update(cx, |view, cx| view.invoke(h, json!(*checked), true, cx));
                    });
                }
                toggle.into_any_element()
            }
            "date_picker" | "time_picker" => match self.inputs.get(key.as_ref()) {
                Some(Editor::Date(state, _)) => style(
                    DatePicker::new(state)
                        .small()
                        .appearance(false)
                        .w_full()
                        .h(px(ui::CONTROL))
                        .flex()
                        .flex_col()
                        .justify_center()
                        .border_1()
                        .border_color(rgb(ui::forms::BORDER))
                        .bg(rgb(crate::sdk::ui::theme::color(ui::CANVAS)))
                        .when(
                            state.focus_handle(cx).contains_focused(window, cx),
                            |picker| picker.border_color(cx.theme().ring),
                        )
                        .text_size(px(ui::BODY))
                        .rounded(px(ui::RADIUS))
                        .cleanable(true)
                        .disabled(self.read_only || p["disabled"] == true),
                    node,
                )
                .into_any_element(),
                Some(Editor::Time(state)) => style(
                    TimeField::new(state)
                        .small()
                        .w_full()
                        .h(px(ui::CONTROL))
                        .text_size(px(ui::BODY))
                        .rounded(px(ui::RADIUS))
                        .disabled(self.read_only || p["disabled"] == true),
                    node,
                )
                .into_any_element(),
                _ => ui::error("Picker requires a stable id outside List rows").into_any_element(),
            },
            "action_menu" | "context_menu" => {
                let items = p["items"].as_array().cloned().unwrap_or_default();
                let weak = self.weak.clone();
                let callback = handler(p, "onAction");
                let menu = move |menu: gpui_kit::component::menu::PopupMenu, _: &mut Window, _: &mut Context<gpui_kit::component::menu::PopupMenu>| {
                    items.iter().fold(menu, |menu,item| {
                        let weak = weak.clone(); let value = item["id"].clone();
                        let mut label = text(item,"label");
                        if let Some(shortcut) = item["shortcut"].as_str() { label.push_str(&format!("    {shortcut}")); }
                        menu.item(PopupMenuItem::new(label).disabled(item["disabled"] == true).on_click(move |_,_,cx| {
                            if let Some(h) = callback { let _ = weak.update(cx,|view,cx| view.invoke(h,value.clone(),true,cx)); }
                        }))
                    })
                };
                if node.kind == "context_menu" {
                    style(div(), node)
                        .id(id)
                        .children(self.children(node, window, cx))
                        .context_menu(menu)
                        .into_any_element()
                } else {
                    ui::forms::secondary_button(id, text(p, "label"))
                        .disabled(self.read_only || p["disabled"] == true)
                        .dropdown_menu(menu)
                        .into_any_element()
                }
            }
            "select" => {
                let options: Rc<Vec<(Value, String)>> = Rc::new(
                    p["options"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .map(|option| match option {
                            Value::Object(_) => {
                                let label = text(option, "label");
                                let value = option.get("value").cloned().unwrap_or(json!(label));
                                (value, label)
                            }
                            other => (other.clone(), text(&json!({"v": other}), "v")),
                        })
                        .collect(),
                );
                let current = p["value"].clone();
                let shown = options
                    .iter()
                    .find(|(value, _)| *value == current)
                    .map(|(_, label)| label.clone())
                    .unwrap_or_else(|| text(p, "placeholder"));
                let label = p["label"].as_str().unwrap_or("Choose").to_owned();
                let change = handler(p, "onChange");
                let weak = self.weak.clone();
                let mut trigger = ui::forms::select_trigger(id, label, shown);
                if p["quiet"] == true {
                    // A setting inside another surface (a composer's model
                    // picker): a borderless pill sized to its value.
                    use gpui_kit::component::button::ButtonVariants as _;
                    trigger = trigger
                        .ghost()
                        .border_0()
                        .w_auto()
                        .max_w(px(220.))
                        .h(px(28.))
                        .px(px(10.))
                        .rounded(px(14.))
                        .text_size(px(12.5))
                        .text_color(rgb(ui::theme::get(1)));
                }
                style(trigger, node)
                    .disabled(self.read_only || p["disabled"] == true)
                    .dropdown_menu(move |menu, _, _| {
                        options.iter().fold(menu, |menu, (value, label)| {
                            let weak = weak.clone();
                            let value = value.clone();
                            let checked = value == current;
                            menu.item(PopupMenuItem::new(label.clone()).checked(checked).on_click(
                                move |_, _, cx| {
                                    if let Some(h) = change {
                                        let _ = weak.update(cx, |view, cx| {
                                            view.invoke(h, value.clone(), true, cx)
                                        });
                                    }
                                },
                            ))
                        })
                    })
                    .into_any_element()
            }
            "tabs" => {
                let labels: Vec<String> = p["items"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|item| text(&json!({"v": item}), "v"))
                    .collect();
                let refs: Vec<&str> = labels.iter().map(String::as_str).collect();
                let selected = p["selected"].as_u64().unwrap_or(0) as usize;
                let mut tabs = ui::tabs(id, &refs, selected);
                if p["underline"] == true {
                    tabs = tabs.underline();
                }
                if let Some(h) = handler(p, "onChange") {
                    let weak = self.weak.clone();
                    tabs = tabs.on_click(move |index, _, cx| {
                        let _ = weak.update(cx, |view, cx| view.invoke(h, json!(*index), true, cx));
                    });
                }
                // Page navigation rules off the whole row; a mode control
                // keeps its own width.
                let underline = p["underline"] == true;
                ui::row()
                    .when(underline, |row| row.w_full())
                    .child(if underline {
                        tabs.flex_1()
                    } else {
                        tabs.w_auto()
                    })
                    .into_any_element()
            }
            "progress" => {
                let value = p["value"].as_f64().unwrap_or(0.).clamp(0., 1.) as f32;
                let fill = color(&p["color"]).unwrap_or(rgb(ui::theme::get(10)).into());
                style(
                    div()
                        .w_full()
                        .h(px(4.))
                        .flex_shrink_0()
                        .rounded(px(2.))
                        .bg(rgb(crate::sdk::ui::theme::color(ui::INSET)))
                        .overflow_hidden()
                        .child(div().h_full().w(relative(value)).bg(fill)),
                    node,
                )
                .into_any_element()
            }
            "divider" => style(
                div()
                    .w_full()
                    .h(px(1.))
                    .flex_shrink_0()
                    .bg(rgb(crate::sdk::ui::theme::color(ui::RULE))),
                node,
            )
            .into_any_element(),
            "spacer" => div().flex_1().into_any_element(),
            "empty" => ui::empty(text(p, "title"), text(p, "detail")).into_any_element(),
            "loading" => ui::loading().into_any_element(),
            "error" => ui::error(text(p, "text")).into_any_element(),
            "notice" => ui::notice(text(p, "title"), text(p, "detail")).into_any_element(),
            "table" => self.table(node, window, cx),
            "list" => {
                let count = p["count"].as_u64().unwrap_or(0) as usize;
                let Some(row) = handler(p, "row") else {
                    return ui::error("List needs row: (index) => element").into_any_element();
                };
                let build = Build {
                    inputs: Rc::default(),
                    ..self.clone()
                };
                let base = node.path.clone();
                let scroll = {
                    let mut scrolls = self.shared.scrolls.borrow_mut();
                    let (handle, applied) = scrolls
                        .entry(key.to_string())
                        .or_insert_with(|| (UniformListScrollHandle::new(), None));
                    let target = p["scrollTo"].as_u64().filter(|i| (*i as usize) < count);
                    if let Some(index) = target
                        && target != *applied
                    {
                        handle.scroll_to_item(index as usize, ScrollStrategy::Nearest);
                    }
                    *applied = target;
                    handle.clone()
                };
                style(
                    uniform_list(id, count, move |range, window, cx| {
                        range
                            .map(|i| match build.shared.row(row, i, &base) {
                                // A stretching column makes every row span the list width.
                                Ok(node) => div()
                                    .w_full()
                                    .flex()
                                    .flex_col()
                                    .child(build.node(&node, window, cx))
                                    .into_any_element(),
                                Err(error) => ui::caption(error).into_any_element(),
                            })
                            .collect::<Vec<_>>()
                    })
                    .track_scroll(&scroll)
                    .w_full()
                    .flex_1()
                    .min_h_0(),
                    node,
                )
                .into_any_element()
            }
            _ => self.component(node, window, cx),
        }
    }
}
