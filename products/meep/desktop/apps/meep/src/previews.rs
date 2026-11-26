use super::tables::extension;
use super::*;
use meep_ui::gpui_kit::component::Icon;
use std::cell::RefCell;
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
        Kind::Image(format) => image(path, bytes, format),
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
}

fn image(path: &str, bytes: &[u8], format: ImageFormat) -> Div {
    let picture = IMAGE.with_borrow_mut(|held| match held {
        Some((p, n, picture)) if p == path && *n == bytes.len() => picture.clone(),
        _ => {
            let picture = Arc::new(Image::from_bytes(format, bytes.to_vec()));
            *held = Some((path.to_owned(), bytes.len(), picture.clone()));
            picture
        }
    });
    div()
        .w_full()
        .flex()
        .justify_center()
        .p(px(16.))
        .rounded(px(10.))
        .bg(rgb(ui::theme::color(ui::INSET)))
        .child(
            img(picture)
                .max_w_full()
                .max_h(px(620.))
                .object_fit(ObjectFit::Contain)
                .rounded(px(4.)),
        )
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
        return ui::column()
            .w_full()
            .gap(px(12.))
            .child(
                div()
                    .id(SharedString::from(format!("poster-{path}")))
                    .role(Role::Button)
                    .aria_label(label)
                    .cursor_pointer()
                    .relative()
                    .w_full()
                    .flex()
                    .justify_center()
                    .p(px(16.))
                    .rounded(px(10.))
                    .bg(rgb(ui::theme::color(ui::INSET)))
                    .child(
                        img(picture)
                            .max_w_full()
                            .max_h(px(560.))
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
