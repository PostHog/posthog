//! The app's Dock tile. Its badge counts the agent requests waiting for an
//! answer, so they are visible from anywhere, the way Mail counts unread mail.

/// Set a host-supplied icon in a hot-reload build whose bundle lacks an icon.
pub fn set_dev_icon(_icon: &[u8]) {
    #[cfg(all(target_os = "macos", feature = "hot-reload", not(test)))]
    {
        use objc2::{AnyThread, class, msg_send, runtime::AnyObject};
        use objc2_app_kit::NSImage;
        use objc2_foundation::NSData;
        if objc2::MainThreadMarker::new().is_none() {
            return;
        }
        let data = NSData::with_bytes(_icon);
        let Some(image) = NSImage::initWithData(NSImage::alloc(), &data) else {
            return;
        };
        // SAFETY: NSApplication and setApplicationIconImage: are plain AppKit
        // calls made on the main thread with a valid NSImage.
        unsafe {
            let app: *mut AnyObject = msg_send![class!(NSApplication), sharedApplication];
            if !app.is_null() {
                let _: () = msg_send![app, setApplicationIconImage: &*image];
            }
        }
    }
}

/// Show `count` on the Dock icon, or clear the badge at zero.
pub fn set_badge(count: usize) {
    #[cfg(all(target_os = "macos", not(test)))]
    {
        use objc2::{class, msg_send, runtime::AnyObject};
        use objc2_foundation::NSString;
        // Only the main thread may touch AppKit; the window renders there.
        if objc2::MainThreadMarker::new().is_none() {
            return;
        }
        let label = (count > 0).then(|| NSString::from_str(&count.to_string()));
        // SAFETY: NSApplication, its dock tile and setBadgeLabel: are plain
        // AppKit calls made on the main thread; a nil label clears the badge.
        unsafe {
            let app: *mut AnyObject = msg_send![class!(NSApplication), sharedApplication];
            if app.is_null() {
                return;
            }
            let tile: *mut AnyObject = msg_send![app, dockTile];
            if tile.is_null() {
                return;
            }
            let _: () = msg_send![tile, setBadgeLabel: label.as_deref()];
        }
    }
    #[cfg(any(not(target_os = "macos"), test))]
    let _ = count;
}
