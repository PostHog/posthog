use super::tables::extension;
use super::*;
use meep_ui::gpui_kit::component::{Disableable, Icon};
use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::path::PathBuf;

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Table,
    Markdown,
    Code(&'static str),
    Image(ImageFormat),
    Video,
    Audio,
    Pdf,
    Text,
}

fn kind(path: &str) -> Kind {
    match extension(path).as_str() {
        "csv" | "tsv" | "json" => Kind::Table,
        "md" | "markdown" | "mdx" => Kind::Markdown,
        "png" => Kind::Image(ImageFormat::Png),
        "jpg" | "jpeg" => Kind::Image(ImageFormat::Jpeg),
        "gif" => Kind::Image(ImageFormat::Gif),
        "webp" => Kind::Image(ImageFormat::Webp),
        "svg" => Kind::Image(ImageFormat::Svg),
        "bmp" => Kind::Image(ImageFormat::Bmp),
        "tif" | "tiff" => Kind::Image(ImageFormat::Tiff),
        "mp4" | "mov" | "m4v" | "webm" | "mkv" | "avi" => Kind::Video,
        "mp3" | "wav" | "m4a" | "aac" | "ogg" | "flac" => Kind::Audio,
        "pdf" => Kind::Pdf,
        "rs" => Kind::Code("rust"),
        "py" => Kind::Code("python"),
        "ts" | "tsx" => Kind::Code("typescript"),
        "js" | "jsx" | "mjs" => Kind::Code("javascript"),
        "go" => Kind::Code("go"),
        "rb" => Kind::Code("ruby"),
        "java" => Kind::Code("java"),
        "kt" => Kind::Code("kotlin"),
        "swift" => Kind::Code("swift"),
        "c" | "h" => Kind::Code("c"),
        "cpp" | "cc" | "hpp" => Kind::Code("cpp"),
        "sql" => Kind::Code("sql"),
        "sh" | "bash" | "zsh" => Kind::Code("bash"),
        "yaml" | "yml" => Kind::Code("yaml"),
        "toml" => Kind::Code("toml"),
        "html" | "htm" => Kind::Code("html"),
        "css" => Kind::Code("css"),
        "xml" => Kind::Code("xml"),
        _ => Kind::Text,
    }
}

pub(super) fn glyph(path: &str) -> Glyph {
    match kind(path) {
        Kind::Table => Glyph::Table2,
        Kind::Code(_) => Glyph::FileCode,
        Kind::Image(_) => Glyph::Image,
        Kind::Video => Glyph::Video,
        Kind::Audio => Glyph::Music,
        Kind::Markdown | Kind::Pdf | Kind::Text => Glyph::FileText,
    }
}

pub(super) fn render(path: &str, bytes: &[u8], cx: &Context<Desktop>) -> Div {
    match kind(path) {
        Kind::Table if super::tables::read(path, bytes).is_ok() => {
            super::tables::render(path, bytes)
        }
        Kind::Table => text_view(path, bytes, "json", cx),
        Kind::Markdown => match std::str::from_utf8(bytes) {
            Ok(text) => div()
                .w_full()
                .max_w(px(ui::READING_MEASURE))
                .mx_auto()
                .child(meep_shell::transcript::chat_markdown(
                    SharedString::from(format!("file-md-{path}")),
                    text.chars().take(200_000).collect(),
                )),
            Err(_) => handoff(path, bytes, cx),
        },
        Kind::Code(lang) => text_view(path, bytes, lang, cx),
        Kind::Image(format) => image(path, bytes, format, cx),
        Kind::Video | Kind::Audio | Kind::Pdf => handoff(path, bytes, cx),
        Kind::Text => match std::str::from_utf8(bytes) {
            Ok(text) => div()
                .w_full()
                .max_w(px(ui::READING_MEASURE))
                .mx_auto()
                .line_height(relative(1.6))
                .whitespace_normal()
                .child(text.chars().take(80_000).collect::<String>()),
            Err(_) => handoff(path, bytes, cx),
        },
    }
}

fn text_view(path: &str, bytes: &[u8], lang: &str, cx: &Context<Desktop>) -> Div {
    let Ok(text) = std::str::from_utf8(bytes) else {
        return handoff(path, bytes, cx);
    };
    let text: String = text.chars().take(80_000).collect();
    let longest = text.split(|c| c != '`').map(str::len).max().unwrap_or(0);
    let fence = "`".repeat(longest.max(2) + 1);
    div()
        .w_full()
        .min_w_0()
        .child(meep_shell::transcript::chat_markdown(
            SharedString::from(format!("file-code-{path}")),
            format!("{fence}{lang}\n{}\n{fence}", text.trim_end()),
        ))
}

thread_local! {
    static IMAGE: RefCell<Option<(String, usize, Arc<Image>)>> = const { RefCell::new(None) };
    static ZOOM: RefCell<HashMap<String, usize>> = RefCell::new(HashMap::new());
    static AREA: Cell<(f32, f32)> = const { Cell::new((720., 560.)) };
}

const ZOOM_STEPS: [f32; 5] = [0., 0.5, 1., 2., 4.];
const STAGE_PAD: f32 = 16.;

fn zoom_step(path: &str) -> usize {
    ZOOM.with_borrow(|z| z.get(path).copied().unwrap_or(0))
}

fn set_zoom(path: &str, step: usize) {
    ZOOM.with_borrow_mut(|z| {
        if step == 0 {
            z.remove(path);
        } else {
            z.insert(path.to_owned(), step);
        }
    });
}

fn area_probe(cx: &Context<Desktop>) -> impl IntoElement {
    let desktop = cx.entity();
    canvas(
        move |bounds, window, cx| {
            let pane = desktop.read(cx).content_scroll.clone();
            let frame = pane.bounds();
            if frame.size.height <= px(0.) {
                return;
            }
            let top = bounds.origin.y - pane.offset().y;
            let height = (f32::from(frame.bottom() - top) - 16.).max(320.);
            let width = f32::from(bounds.size.width).max(1.);
            let (w, h) = AREA.get();
            if (w - width).abs() > 1. || (h - height).abs() > 1. {
                AREA.set((width, height));
                let id = desktop.entity_id();
                window.on_next_frame(move |_, cx| cx.notify(id));
            }
        },
        |_, _, _, _| {},
    )
    .w_full()
    .h(px(0.))
}

fn stage(height: f32) -> Div {
    div()
        .relative()
        .w_full()
        .h(px(height))
        .flex_none()
        .rounded(px(10.))
        .overflow_hidden()
        .bg(rgb(ui::theme::color(ui::INSET)))
}

fn image(path: &str, bytes: &[u8], format: ImageFormat, cx: &Context<Desktop>) -> Div {
    let picture = IMAGE.with_borrow_mut(|held| match held {
        Some((p, n, picture)) if p == path && *n == bytes.len() => picture.clone(),
        _ => {
            let picture = Arc::new(Image::from_bytes(format, bytes.to_vec()));
            *held = Some((path.to_owned(), bytes.len(), picture.clone()));
            picture
        }
    });
    let natural = dimensions(bytes, format);
    let (area_w, area_h) = AREA.get();
    let step = if natural.is_some() {
        zoom_step(path)
    } else {
        0
    };
    let view = match natural {
        Some((w, h)) if step > 0 => {
            let scale = ZOOM_STEPS[step];
            div()
                .id(SharedString::from(format!("image-zoom-{path}")))
                .size_full()
                .flex()
                .items_start()
                .overflow_scroll()
                .child(
                    div()
                        .flex_none()
                        .min_w_full()
                        .min_h_full()
                        .flex()
                        .items_center()
                        .justify_center()
                        .p(px(STAGE_PAD))
                        .child(img(picture).flex_none().w(px(w * scale)).h(px(h * scale))),
                )
                .into_any_element()
        }
        _ => div()
            .size_full()
            .flex()
            .items_center()
            .justify_center()
            .p(px(STAGE_PAD))
            .child(
                div()
                    .size_full()
                    .when_some(natural, |d, (w, h)| d.max_w(px(w * 2.)).max_h(px(h * 2.)))
                    .child(img(picture).size_full().object_fit(ObjectFit::Contain)),
            )
            .into_any_element(),
    };
    ui::column()
        .w_full()
        .child(area_probe(cx))
        .child(stage(area_h).child(view).when_some(natural, |d, (w, h)| {
            let fit = ((area_w - STAGE_PAD * 2.) / w)
                .min((area_h - STAGE_PAD * 2.) / h)
                .clamp(0.01, 2.);
            d.child(zoom_controls(path, step, fit, cx))
        }))
}

fn zoom_controls(path: &str, step: usize, fit: f32, cx: &Context<Desktop>) -> Div {
    let last = ZOOM_STEPS.len() - 1;
    let zoom_in = match step {
        0 => (1..=last).find(|&i| ZOOM_STEPS[i] > fit * 1.01),
        s if s < last => Some(s + 1),
        _ => None,
    };
    let zoom_out = match step {
        0 => (1..=last).rev().find(|&i| ZOOM_STEPS[i] < fit * 0.99),
        s => Some(s - 1),
    };
    let label = match step {
        0 => "Fit".to_owned(),
        s => format!("{}%", (ZOOM_STEPS[s] * 100.).round() as u32),
    };
    let button = |id: &'static str, glyph: Glyph, text: &'static str, target: Option<usize>| {
        let key = path.to_owned();
        ui::icon_button(id, glyph, text)
            .tooltip(text)
            .disabled(target.is_none())
            .on_click(cx.listener(move |_, _, _, cx| {
                if let Some(target) = target {
                    set_zoom(&key, target);
                    cx.notify();
                }
            }))
    };
    let key = path.to_owned();
    div().absolute().bottom(px(12.)).right(px(12.)).child(
        ui::row()
            .gap(px(2.))
            .p(px(2.))
            .rounded_full()
            .border_1()
            .border_color(ui::ink(0x14))
            .bg(rgb(ui::theme::color(ui::CANVAS)))
            .shadow_sm()
            .child(button("image-zoom-out", Glyph::Minus, "Zoom out", zoom_out))
            .child(
                div()
                    .id("image-zoom-fit")
                    .role(Role::Button)
                    .aria_label("Fit to view")
                    .min_w(px(44.))
                    .px(px(4.))
                    .flex()
                    .justify_center()
                    .text_size(px(ui::SMALL))
                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                    .when(step > 0, |d| d.cursor_pointer())
                    .child(label)
                    .on_click(cx.listener(move |_, _, _, cx| {
                        if zoom_step(&key) > 0 {
                            set_zoom(&key, 0);
                            cx.notify();
                        }
                    })),
            )
            .child(button("image-zoom-in", Glyph::Plus, "Zoom in", zoom_in)),
    )
}

fn dimensions(bytes: &[u8], format: ImageFormat) -> Option<(f32, f32)> {
    let le16 = |i: usize| Some(u16::from_le_bytes([*bytes.get(i)?, *bytes.get(i + 1)?]) as u32);
    let be32 = |i: usize| Some(u32::from_be_bytes(bytes.get(i..i + 4)?.try_into().ok()?));
    let le32 = |i: usize| Some(u32::from_le_bytes(bytes.get(i..i + 4)?.try_into().ok()?));
    let (w, h) = match format {
        ImageFormat::Png => (be32(16)? as f32, be32(20)? as f32),
        ImageFormat::Gif => (le16(6)? as f32, le16(8)? as f32),
        ImageFormat::Bmp => (le32(18)? as f32, (le32(22)? as i32).unsigned_abs() as f32),
        ImageFormat::Jpeg => jpeg_size(bytes)?,
        ImageFormat::Webp => match bytes.get(12..16)? {
            b"VP8 " => ((le16(26)? & 0x3fff) as f32, (le16(28)? & 0x3fff) as f32),
            b"VP8L" => {
                let b = le32(21)?;
                (((b & 0x3fff) + 1) as f32, (((b >> 14) & 0x3fff) + 1) as f32)
            }
            b"VP8X" => (
                ((le32(24)? & 0xff_ffff) + 1) as f32,
                ((le32(27)? & 0xff_ffff) + 1) as f32,
            ),
            _ => return None,
        },
        ImageFormat::Svg => svg_size(bytes)?,
        _ => return None,
    };
    (w > 0. && h > 0.).then_some((w, h))
}

fn jpeg_size(bytes: &[u8]) -> Option<(f32, f32)> {
    let mut i = 2;
    while i + 9 < bytes.len() {
        if bytes[i] != 0xff {
            return None;
        }
        let marker = bytes[i + 1];
        if marker == 0xff {
            i += 1;
            continue;
        }
        if (0xc0..=0xcf).contains(&marker) && !matches!(marker, 0xc4 | 0xc8 | 0xcc) {
            let h = u16::from_be_bytes([bytes[i + 5], bytes[i + 6]]);
            let w = u16::from_be_bytes([bytes[i + 7], bytes[i + 8]]);
            return Some((w as f32, h as f32));
        }
        i += 2 + u16::from_be_bytes([bytes[i + 2], bytes[i + 3]]) as usize;
    }
    None
}

fn svg_size(bytes: &[u8]) -> Option<(f32, f32)> {
    let text = String::from_utf8_lossy(&bytes[..bytes.len().min(8192)]);
    let start = text.find("<svg")?;
    let tag = &text[start..start + text[start..].find('>')?];
    let attr = |name: &str| -> Option<String> {
        let key = format!("{name}=");
        let (i, _) = tag
            .match_indices(key.as_str())
            .find(|(i, _)| tag[..*i].ends_with(char::is_whitespace))?;
        let rest = &tag[i + key.len()..];
        let quote = rest.chars().next().filter(|c| *c == '"' || *c == '\'')?;
        let rest = &rest[1..];
        Some(rest[..rest.find(quote)?].trim().to_owned())
    };
    let number = |v: String| {
        v.trim_end_matches("px")
            .trim()
            .parse::<f32>()
            .ok()
            .filter(|n| *n > 0.)
    };
    match (
        attr("width").and_then(number),
        attr("height").and_then(number),
    ) {
        (Some(w), Some(h)) => Some((w, h)),
        _ => {
            let view: Vec<f32> = attr("viewBox")?
                .split(|c: char| c == ',' || c.is_whitespace())
                .filter_map(|p| p.parse().ok())
                .collect();
            Some((*view.get(2)?, *view.get(3)?))
        }
    }
}

enum Poster {
    Pending,
    Ready(Arc<Image>),
    Missing,
}

static POSTERS: std::sync::LazyLock<std::sync::Mutex<HashMap<PathBuf, Poster>>> =
    std::sync::LazyLock::new(Default::default);

fn local_copy(path: &str, bytes: &[u8]) -> PathBuf {
    let name = path.rsplit('/').next().unwrap_or(path);
    let key: String = path
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
        .collect();
    std::env::temp_dir()
        .join("meep-files")
        .join(format!("{key}-{}", bytes.len()))
        .join(name)
}

fn poster(path: &str, bytes: &[u8], cx: &Context<Desktop>) -> Option<Arc<Image>> {
    if !matches!(kind(path), Kind::Video | Kind::Pdf) {
        return None;
    }
    let at = local_copy(path, bytes);
    let mut posters = POSTERS.lock().ok()?;
    match posters.get(&at) {
        Some(Poster::Ready(image)) => return Some(image.clone()),
        Some(_) => return None,
        None => {}
    }
    posters.insert(at.clone(), Poster::Pending);
    let bytes = bytes.to_vec();
    cx.spawn(async move |this, cx| {
        let made = cx
            .background_executor()
            .spawn(async move {
                let dir = at.parent()?.to_path_buf();
                std::fs::create_dir_all(&dir).ok()?;
                std::fs::write(&at, &bytes).ok()?;
                std::process::Command::new("/usr/bin/qlmanage")
                    .args(["-t", "-s", "1280", "-o"])
                    .arg(&dir)
                    .arg(&at)
                    .output()
                    .ok()?;
                let png =
                    std::fs::read(dir.join(format!("{}.png", at.file_name()?.to_string_lossy())))
                        .ok()?;
                Some((at, Arc::new(Image::from_bytes(ImageFormat::Png, png))))
            })
            .await;
        if let Ok(mut posters) = POSTERS.lock() {
            match made {
                Some((at, image)) => {
                    posters.insert(at, Poster::Ready(image));
                }
                None => posters.values_mut().for_each(|p| {
                    if matches!(p, Poster::Pending) {
                        *p = Poster::Missing
                    }
                }),
            }
        }
        let _ = this.update(cx, |_, cx| cx.notify());
    })
    .detach();
    None
}

fn open_in_system(path: &str, bytes: &[u8], cx: &App) {
    let at = local_copy(path, bytes);
    let written = at.exists()
        || at
            .parent()
            .is_some_and(|dir| std::fs::create_dir_all(dir).is_ok())
            && std::fs::write(&at, bytes).is_ok();
    if written {
        cx.open_with_system(&at);
    }
}

fn handoff(path: &str, bytes: &[u8], cx: &Context<Desktop>) -> Div {
    let name = path.rsplit('/').next().unwrap_or(path).to_owned();
    let (label, what) = match kind(path) {
        Kind::Video => ("Play in the default app", "Video"),
        Kind::Audio => ("Play in the default app", "Audio"),
        Kind::Pdf => ("Open in the default app", "PDF"),
        _ => ("Open in the default app", "File"),
    };
    let size = super::pages::human_size(bytes.len());
    let open = {
        let (path, bytes) = (path.to_owned(), bytes.to_vec());
        move |_: &mut Desktop, _: &mut Window, cx: &mut Context<Desktop>| {
            open_in_system(&path, &bytes, cx)
        }
    };
    if let Some(picture) = poster(path, bytes, cx) {
        let video = kind(path) == Kind::Video;
        let (play_path, play_bytes) = (path.to_owned(), bytes.to_vec());
        let height = (AREA.get().1 - 60.).max(240.);
        return ui::column()
            .w_full()
            .gap(px(12.))
            .child(area_probe(cx))
            .child(
                div()
                    .id(SharedString::from(format!("poster-{path}")))
                    .role(Role::Button)
                    .aria_label(label)
                    .cursor_pointer()
                    .relative()
                    .w_full()
                    .h(px(height))
                    .flex_none()
                    .flex()
                    .items_center()
                    .justify_center()
                    .p(px(STAGE_PAD))
                    .rounded(px(10.))
                    .bg(rgb(ui::theme::color(ui::INSET)))
                    .child(
                        img(picture)
                            .size_full()
                            .object_fit(ObjectFit::Contain)
                            .rounded(px(6.)),
                    )
                    .when(video, |d| {
                        d.child(
                            div()
                                .absolute()
                                .inset_0()
                                .flex()
                                .items_center()
                                .justify_center()
                                .child(
                                    div()
                                        .size(px(64.))
                                        .rounded_full()
                                        .bg(gpui::rgba(0x000000a6))
                                        .flex()
                                        .items_center()
                                        .justify_center()
                                        .child(
                                            Icon::new(Glyph::Play)
                                                .size(px(26.))
                                                .text_color(gpui::rgb(0xffffff)),
                                        ),
                                ),
                        )
                    })
                    .tooltip(move |w, cx| {
                        meep_ui::gpui_kit::component::tooltip::Tooltip::new(label).build(w, cx)
                    })
                    .on_click(move |_, _, cx| open_in_system(&play_path, &play_bytes, cx)),
            )
            .child(
                ui::row()
                    .gap(px(8.))
                    .child(ui::caption(format!("{what} · {size}")).flex_1())
                    .child(
                        control("open-in-system", label, false, cx, open).icon(Glyph::ExternalLink),
                    ),
            );
    }
    ui::column()
        .w_full()
        .items_center()
        .gap(px(14.))
        .py(px(56.))
        .rounded(px(10.))
        .bg(rgb(ui::theme::color(ui::INSET)))
        .child(
            div()
                .size(px(56.))
                .rounded(px(14.))
                .bg(ui::ink(0x0a))
                .flex()
                .items_center()
                .justify_center()
                .child(
                    Icon::new(glyph(path))
                        .size(px(26.))
                        .text_color(rgb(ui::theme::color(ui::SECONDARY))),
                ),
        )
        .child(
            ui::column()
                .items_center()
                .gap(px(2.))
                .child(div().font_weight(FontWeight::MEDIUM).child(name))
                .child(ui::caption(format!("{what} · {size}"))),
        )
        .child(
            control("open-in-system", label, false, cx, open)
                .icon(Glyph::ExternalLink)
                .self_center(),
        )
}
