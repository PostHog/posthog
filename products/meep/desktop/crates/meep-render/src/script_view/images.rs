//! Native image presentation. Only the broker can resolve a source to bytes.
use super::*;

fn frame(node: &Node) -> Stateful<Div> {
    style(
        div()
            .id(node.key.clone())
            .w(px(240.))
            .h(px(144.))
            .max_w(relative(1.))
            .overflow_hidden(),
        node,
    )
}

fn placeholder(frame: Stateful<Div>, message: impl Into<SharedString>) -> Stateful<Div> {
    frame
        .flex()
        .flex_col()
        .items_center()
        .justify_center()
        .gap(px(6.))
        .px(px(8.))
        .bg(rgb(ui::theme::color(ui::INSET)))
        .child(ui::caption(message.into()).text_center().line_clamp(2))
}

#[cfg(target_family = "wasm")]
impl Build {
    pub(super) fn image(&self, node: &Node, _: &mut Window, _: &mut App) -> AnyElement {
        let alt = node.p["alt"].as_str().filter(|alt| !alt.is_empty());
        placeholder(
            frame(node),
            alt.unwrap_or("Image unavailable in this preview")
                .to_owned(),
        )
        .into_any_element()
    }
}

#[cfg(not(target_family = "wasm"))]
pub(super) use native::{Cache, Spec};
#[cfg(not(target_family = "wasm"))]
pub use native::{forget_file_images, forget_remote_images};

#[cfg(not(target_family = "wasm"))]
mod native {
    use super::*;
    use crate::image_source::{ImageSource, MAX_BYTES};
    use base64::{Engine as _, engine::general_purpose::STANDARD};
    use image::{DynamicImage, ImageDecoder as _, ImageFormat, ImageReader, Limits};
    use std::{collections::HashSet, io::Cursor, sync::Arc, time::Duration};

    const CACHE_BYTES: usize = 64 * 1024 * 1024;
    const CACHE_ENTRIES: usize = 128;

    pub(in crate::script_view) struct Spec {
        source: Result<Rc<ImageSource>, SharedString>,
        alt: SharedString,
        fit: fn() -> ObjectFit,
    }

    impl Spec {
        pub(in crate::script_view) fn new(p: &Value) -> Self {
            Self {
                source: ImageSource::parse(&p["source"])
                    .map(Rc::new)
                    .map_err(|error| error.to_string().into()),
                alt: text(p, "alt").into(),
                fit: match p["fit"].as_str() {
                    Some("cover") => || ObjectFit::Cover,
                    Some("fill") => || ObjectFit::Fill,
                    Some("scaleDown") => || ObjectFit::ScaleDown,
                    _ => || ObjectFit::Contain,
                },
            }
        }
    }

    #[derive(Clone)]
    enum State {
        Loading,
        NeedsApproval,
        Ready(Arc<RenderImage>),
        Failed(SharedString),
    }

    struct Entry {
        request: u64,
        state: State,
        touched: Instant,
        viewers: HashSet<EntityId>,
    }

    pub(in crate::script_view) struct Cache {
        pub(in crate::script_view) enabled: bool,
        entries: HashMap<Rc<ImageSource>, Entry>,
        bytes: usize,
        last_request: u64,
        approvals: HashSet<String>,
        approval_error: Option<(String, SharedString)>,
        slots: Arc<tokio::sync::Semaphore>,
    }

    impl Default for Cache {
        fn default() -> Self {
            Self {
                enabled: true,
                entries: HashMap::new(),
                bytes: 0,
                last_request: 0,
                approvals: HashSet::new(),
                approval_error: None,
                slots: Arc::new(tokio::sync::Semaphore::new(4)),
            }
        }
    }

    impl Cache {
        fn remove(&mut self, source: &ImageSource, window: Option<&mut Window>, cx: &mut App) {
            if let Some(entry) = self.entries.remove(source) {
                if let State::Ready(image) = entry.state {
                    self.bytes -= image.as_bytes(0).map_or(0, <[u8]>::len);
                    if let Some(window) = window {
                        // Rendering can still be using this texture in a cached region.
                        window.defer(cx, move |window, cx| cx.drop_image(image, Some(window)));
                    } else {
                        cx.drop_image(image, None);
                    }
                }
                for viewer in entry.viewers {
                    App::notify(cx, viewer);
                }
            }
        }

        fn evictable(&self, ready_only: bool) -> Option<Rc<ImageSource>> {
            self.entries
                .iter()
                .filter(|(_, entry)| {
                    entry.touched.elapsed() > Duration::from_secs(1)
                        && if ready_only {
                            matches!(entry.state, State::Ready(_))
                        } else {
                            !matches!(entry.state, State::Loading)
                        }
                })
                .min_by_key(|(_, entry)| entry.touched)
                .map(|(source, _)| source.clone())
        }

        fn refresh(
            &mut self,
            mut matches: impl FnMut(&ImageSource, &State) -> bool,
            mut window: Option<&mut Window>,
            cx: &mut App,
        ) {
            let stale: Vec<_> = self
                .entries
                .iter()
                .filter(|(source, entry)| matches(source, &entry.state))
                .map(|(source, _)| source.clone())
                .collect();
            for source in stale {
                self.remove(&source, window.as_deref_mut(), cx);
            }
        }

        pub(in crate::script_view) fn release(&mut self, cx: &mut App) {
            for (_, entry) in self.entries.drain() {
                if let State::Ready(image) = entry.state {
                    cx.drop_image(image, None);
                }
            }
        }
    }

    impl Build {
        pub(in crate::script_view) fn image(
            &self,
            node: &Node,
            window: &mut Window,
            cx: &mut App,
        ) -> AnyElement {
            let spec = node.image.as_ref().unwrap();
            let frame = frame(node);
            let source = match &spec.source {
                Ok(source) => source,
                Err(error) => return placeholder(frame, error.clone()).into_any_element(),
            };
            let mut cache = self.shared.images.borrow_mut();
            if !cache.enabled || self.read_only {
                let alt = if spec.alt.is_empty() {
                    "Image unavailable".into()
                } else {
                    spec.alt.clone()
                };
                return placeholder(frame, alt).into_any_element();
            }
            let viewer = window.current_view();
            let state = if let Some(entry) = cache.entries.get_mut(source) {
                entry.touched = Instant::now();
                entry.viewers.insert(viewer);
                entry.state.clone()
            } else {
                if cache.entries.len() == CACHE_ENTRIES {
                    let Some(oldest) = cache.evictable(false) else {
                        return placeholder(frame, "Too many images on screen").into_any_element();
                    };
                    cache.remove(&oldest, Some(window), cx);
                }
                cache.last_request += 1;
                let request = cache.last_request;
                cache.entries.insert(
                    source.clone(),
                    Entry {
                        request,
                        state: State::Loading,
                        touched: Instant::now(),
                        viewers: HashSet::from([viewer]),
                    },
                );
                let (weak, source) = (self.weak.clone(), source.clone());
                cx.defer(move |cx| {
                    let _ = weak.update(cx, |this, cx| this.load_image(source, request, cx));
                });
                State::Loading
            };
            match state {
                State::Ready(image) => frame
                    .when(!spec.alt.is_empty(), |el| {
                        el.role(Role::Image).aria_label(spec.alt.clone())
                    })
                    .child(img(image).size_full().object_fit((spec.fit)()))
                    .into_any_element(),
                State::Loading => placeholder(frame, "Loading image…").into_any_element(),
                State::Failed(message) => placeholder(frame, message).into_any_element(),
                State::NeedsApproval => {
                    let domain = source.domain().unwrap();
                    if cache.approvals.contains(domain) {
                        return placeholder(frame, "Waiting for approval…").into_any_element();
                    }
                    let caption = cache
                        .approval_error
                        .as_ref()
                        .filter(|(host, _)| host == domain)
                        .map_or_else(
                            || SharedString::from(domain.to_owned()),
                            |(_, error)| error.clone(),
                        );
                    let (weak, source) = (self.weak.clone(), source.clone());
                    placeholder(frame, caption)
                        .child(
                            ui::forms::secondary_button(
                                SharedString::from(format!("{}-load-image", node.key)),
                                "Load image",
                            )
                            .on_click(move |_, _, cx| {
                                cx.stop_propagation();
                                let _ = weak
                                    .update(cx, |this, cx| this.approve_image(source.clone(), cx));
                            }),
                        )
                        .into_any_element()
                }
            }
        }
    }

    impl ScriptView {
        fn load_image(&self, source: Rc<ImageSource>, request: u64, cx: &mut Context<Self>) {
            let slots = self.shared.images.borrow().slots.clone();
            let context = self.context.clone();
            cx.spawn(async move |this, cx| {
                let Ok(_slot) = slots.acquire().await else {
                    return;
                };
                let state = cx.update(|cx| {
                    this.upgrade().is_some_and(|view| {
                        view.read(cx)
                            .shared
                            .images
                            .borrow()
                            .entries
                            .get(&source)
                            .is_some_and(|entry| entry.request == request)
                    })
                });
                if !state {
                    return;
                }
                let rx = context.request(
                    "native.images.load",
                    json!({"_image_element":true,"source":source.to_value()}),
                );
                let outcome = match rx.recv().await {
                    Ok(Ok(value))
                        if source
                            .domain()
                            .is_some_and(|host| value["approval_required"] == host) =>
                    {
                        State::NeedsApproval
                    }
                    Ok(Ok(value)) => {
                        cx.background_executor()
                            .spawn(async move {
                                match decode(&value) {
                                    Ok(image) => State::Ready(image),
                                    Err(error) => State::Failed(error.into()),
                                }
                            })
                            .await
                    }
                    Ok(Err(error)) => State::Failed(error.into()),
                    Err(_) => State::Failed("Image could not be loaded".into()),
                };
                let _ = this.update(cx, |this, cx| {
                    let mut cache = this.shared.images.borrow_mut();
                    if cache
                        .entries
                        .get(&source)
                        .is_none_or(|entry| entry.request != request)
                    {
                        return;
                    }
                    let outcome = if let State::Ready(image) = &outcome {
                        let bytes = image.as_bytes(0).map_or(0, <[u8]>::len);
                        while cache.bytes + bytes > CACHE_BYTES {
                            let Some(oldest) = cache.evictable(true) else {
                                break;
                            };
                            cache.remove(&oldest, None, cx);
                        }
                        if cache.bytes + bytes <= CACHE_BYTES {
                            cache.bytes += bytes;
                            outcome
                        } else {
                            State::Failed("Too many large images on screen".into())
                        }
                    } else {
                        outcome
                    };
                    let entry = cache.entries.get_mut(&source).unwrap();
                    entry.state = outcome;
                    for &viewer in &entry.viewers {
                        App::notify(cx, viewer);
                    }
                });
            })
            .detach();
        }

        fn approve_image(&self, source: Rc<ImageSource>, cx: &mut Context<Self>) {
            let domain = source.domain().unwrap().to_owned();
            let mut cache = self.shared.images.borrow_mut();
            if self.context.is_retired()
                || !cache
                    .entries
                    .get(&source)
                    .is_some_and(|entry| matches!(entry.state, State::NeedsApproval))
                || !cache.approvals.insert(domain.clone())
            {
                return;
            }
            cache.approval_error = None;
            for (source, entry) in &cache.entries {
                if source.domain() == Some(&domain) && matches!(entry.state, State::NeedsApproval) {
                    for &viewer in &entry.viewers {
                        App::notify(cx, viewer);
                    }
                }
            }
            let rx = self.context.request(
                "native.images.allow",
                json!({"_image_element":true,"source":source.to_value()}),
            );
            cx.spawn(async move |this, cx| {
                let result = rx
                    .recv()
                    .await
                    .unwrap_or_else(|_| Err("Image approval unavailable".into()));
                let _ = this.update(cx, |this, cx| {
                    let mut cache = this.shared.images.borrow_mut();
                    cache.approvals.remove(&domain);
                    match result {
                        Ok(result) if result["approved"] == true => {
                            cache.refresh(
                                |source, state| {
                                    source.domain() == Some(&domain)
                                        && matches!(state, State::NeedsApproval | State::Loading)
                                },
                                None,
                                cx,
                            );
                        }
                        result => {
                            cache.approval_error =
                                result.err().map(|error| (domain.clone(), error.into()));
                            for (source, entry) in &cache.entries {
                                if source.domain() == Some(&domain)
                                    && matches!(entry.state, State::NeedsApproval)
                                {
                                    for &viewer in &entry.viewers {
                                        App::notify(cx, viewer);
                                    }
                                }
                            }
                        }
                    }
                });
            })
            .detach();
        }
    }

    pub fn forget_remote_images(
        view: &AnyView,
        domains: &[&str],
        window: &mut Window,
        cx: &mut App,
    ) {
        if let Ok(view) = view.clone().downcast::<ScriptView>() {
            view.update(cx, |view, cx| {
                view.shared.images.borrow_mut().refresh(
                    |source, _| {
                        source
                            .domain()
                            .is_some_and(|domain| domains.contains(&domain))
                    },
                    Some(window),
                    cx,
                );
            });
        }
    }

    pub fn forget_file_images(view: &AnyView, removed: &str, window: &mut Window, cx: &mut App) {
        if let Ok(view) = view.clone().downcast::<ScriptView>() {
            view.update(cx, |view, cx| {
                view.shared.images.borrow_mut().refresh(
                    |source, _| matches!(source, ImageSource::Local { id, .. } if id == removed),
                    Some(window),
                    cx,
                );
            });
        }
    }

    fn decode(value: &Value) -> Result<Arc<RenderImage>, &'static str> {
        let encoded = value["bytes"]
            .as_str()
            .filter(|value| value.len() <= MAX_BYTES.div_ceil(3) * 4)
            .ok_or("Image data unavailable")?;
        let bytes = STANDARD.decode(encoded).map_err(|_| "Invalid image data")?;
        decode_bytes(bytes)
    }

    fn decode_bytes(bytes: Vec<u8>) -> Result<Arc<RenderImage>, &'static str> {
        let format = image::guess_format(&bytes)
            .ok()
            .filter(|format| {
                matches!(
                    format,
                    ImageFormat::Png | ImageFormat::Jpeg | ImageFormat::WebP | ImageFormat::Gif
                )
            })
            .ok_or("Use a PNG, JPEG, WebP or GIF image")?;
        let mut reader = ImageReader::with_format(Cursor::new(bytes), format);
        let mut limits = Limits::default();
        limits.max_image_width = Some(8192);
        limits.max_image_height = Some(8192);
        limits.max_alloc = Some(64 * 1024 * 1024);
        reader.limits(limits.clone());
        let mut decoder = reader
            .into_decoder()
            .map_err(|_| "Image is invalid or too large")?;
        limits
            .reserve(decoder.total_bytes())
            .map_err(|_| "Image is too large")?;
        decoder
            .set_limits(limits)
            .map_err(|_| "Image is too large")?;
        let orientation = decoder
            .orientation()
            .map_err(|_| "Image metadata is invalid")?;
        let mut image =
            DynamicImage::from_decoder(decoder).map_err(|_| "Image could not be decoded")?;
        image.apply_orientation(orientation);
        if image.width() > 1600 || image.height() > 1600 {
            image = image.thumbnail(1600, 1600);
        }
        let mut rgba = image.into_rgba8();
        for pixel in rgba.as_chunks_mut::<4>().0 {
            pixel.swap(0, 2);
        }
        Ok(Arc::new(RenderImage::new(vec![image::Frame::new(rgba)])))
    }
}
