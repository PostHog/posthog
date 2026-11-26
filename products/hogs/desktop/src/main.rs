mod api;
mod app;
mod models;
mod theme;

use gpui_kit::assets::Assets;
use gpui_kit::*;

use crate::app::HogsApp;

fn main() {
    let application = gpui_kit::application().with_assets(Assets);
    application.run(move |cx| {
        gpui_kit::init(cx);
        let options = WindowOptions {
            window_bounds: Some(WindowBounds::centered(None, size(px(1180.), px(780.)), cx)),
            window_min_size: Some(size(px(760.), px(520.))),
            titlebar: Some(TitlebarOptions {
                title: Some("Hogs".into()),
                appears_transparent: true,
                traffic_light_position: Some(point(px(14.), px(14.))),
            }),
            ..Default::default()
        };
        gpui_kit::open_window(options, cx, |window, cx| cx.new(|cx| HogsApp::new(window, cx)))
            .expect("Failed to open the Hogs window");
        cx.on_window_closed(|cx, _| {
            if cx.windows().is_empty() {
                cx.quit();
            }
        })
        .detach();
        cx.activate(true);
    });
}
