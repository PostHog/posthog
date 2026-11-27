use super::*;
use std::sync::LazyLock;

pub(super) fn wordmark(width: f32) -> impl IntoElement {
    static ART: LazyLock<[Arc<Image>; 2]> = LazyLock::new(|| {
        [
            include_bytes!("../assets/brand/wordmark.png").as_slice(),
            include_bytes!("../assets/brand/wordmark-dark.png").as_slice(),
        ]
        .map(|bytes| Arc::new(Image::from_bytes(ImageFormat::Png, bytes.to_vec())))
    });
    img(ART[usize::from(ui::theme::is_dark())].clone())
        .w(px(width))
        .h(px(width * 0.34))
        .object_fit(ObjectFit::Contain)
}

#[cfg(target_os = "macos")]
pub(super) fn install_dock_icon() {
    use objc2::{AnyThread, MainThreadMarker};
    use objc2_app_kit::{NSApplication, NSImage};
    use objc2_foundation::NSData;

    let main = MainThreadMarker::new().expect("Meep starts on the AppKit main thread");
    let data = NSData::with_bytes(include_bytes!("../assets/brand/dock-icon.png"));
    if let Some(image) = NSImage::initWithData(NSImage::alloc(), &data) {
        unsafe { NSApplication::sharedApplication(main).setApplicationIconImage(Some(&image)) }
    }
}
