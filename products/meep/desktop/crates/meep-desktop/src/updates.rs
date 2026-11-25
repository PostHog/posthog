//! In-app updates for the distributed app, with Sparkle 2.
//!
//! Release bundles (`scripts/release.sh`) carry
//! `Contents/Frameworks/Sparkle.framework` and an Info.plist naming the update
//! feed (`SUFeedURL`) and the EdDSA public key every update and the feed
//! itself must be signed with (`SUPublicEDKey`, `SURequireSignedFeed`). The
//! framework is loaded at run time, so development builds, which carry
//! neither, have no updater and no menu item. Sparkle asks the user once
//! whether to check automatically, then downloads, verifies and installs
//! updates itself.
use objc2::rc::{Allocated, Retained};
use objc2::runtime::{AnyClass, AnyObject, Bool};
use objc2::{class, msg_send};
use objc2_foundation::NSString;
use std::cell::RefCell;
use std::path::PathBuf;

thread_local! {
    /// The running updater, kept for the life of the app.
    static UPDATER: RefCell<Option<Retained<AnyObject>>> = const { RefCell::new(None) };
}

fn framework() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let path = exe.parent()?.parent()?.join("Frameworks/Sparkle.framework");
    path.is_dir().then_some(path)
}

/// The value of an Info.plist key of the running bundle.
fn info(key: &str) -> Option<String> {
    // SAFETY: NSBundle's main bundle and its info dictionary are read-only
    // Foundation calls; the result is an NSString or nil.
    unsafe {
        let bundle: *mut AnyObject = msg_send![class!(NSBundle), mainBundle];
        if bundle.is_null() {
            return None;
        }
        let value: *mut AnyObject =
            msg_send![bundle, objectForInfoDictionaryKey: &*NSString::from_str(key)];
        let value = value.as_ref()?;
        let string: &NSString = value.downcast_ref()?;
        Some(string.to_string())
    }
}

/// A `SPUStandardUpdaterController` from the bundled framework.
fn controller(start: bool) -> Result<Retained<AnyObject>, String> {
    let path = framework().ok_or("This build has no Sparkle.framework")?;
    if info("SUFeedURL").is_none() || info("SUPublicEDKey").is_none() {
        return Err("Info.plist has no SUFeedURL or SUPublicEDKey".into());
    }
    // SAFETY: loads the signed framework from our own bundle, then calls
    // SPUStandardUpdaterController's designated initializer with no delegates,
    // as Sparkle documents for programmatic setup.
    unsafe {
        let bundle: *mut AnyObject = msg_send![
            class!(NSBundle),
            bundleWithPath: &*NSString::from_str(&path.to_string_lossy())
        ];
        if bundle.is_null() {
            return Err("Sparkle.framework is not a bundle".into());
        }
        let loaded: Bool = msg_send![bundle, load];
        if !loaded.as_bool() {
            return Err("Sparkle.framework did not load".into());
        }
        let class = AnyClass::get(c"SPUStandardUpdaterController")
            .ok_or("Sparkle.framework has no SPUStandardUpdaterController")?;
        let allocated: Allocated<AnyObject> = msg_send![class, alloc];
        let none = std::ptr::null_mut::<AnyObject>();
        let controller: Option<Retained<AnyObject>> = msg_send![
            allocated,
            initWithStartingUpdater: Bool::new(start),
            updaterDelegate: none,
            userDriverDelegate: none
        ];
        controller.ok_or_else(|| "Sparkle's updater did not start".into())
    }
}

/// Starts the updater in a release bundle. Call once, on the main thread,
/// after the app finished launching.
pub fn start() {
    if objc2::MainThreadMarker::new().is_none() || framework().is_none() {
        return;
    }
    match controller(true) {
        Ok(controller) => UPDATER.with(|u| *u.borrow_mut() = Some(controller)),
        Err(error) => eprintln!("Meep updates are off: {error}"),
    }
}

/// Whether this app updates itself (a release bundle whose updater started).
pub fn available() -> bool {
    UPDATER.with(|u| u.borrow().is_some())
}

/// "Check for Updates…": Sparkle shows its own progress and result windows.
pub fn check_now() {
    UPDATER.with(|u| {
        if let Some(controller) = u.borrow().as_ref() {
            // SAFETY: checkForUpdates: is SPUStandardUpdaterController's
            // menu action; a nil sender is allowed.
            unsafe {
                let _: () =
                    msg_send![&**controller, checkForUpdates: std::ptr::null_mut::<AnyObject>()];
            }
        }
    });
}

/// Loads Sparkle and builds the updater without
/// starting it, so the release script can prove a bundle can update itself.
pub fn self_check() -> Result<String, String> {
    let controller = controller(false)?;
    // SAFETY: `updater` is a read-only property of the controller.
    let updater: *mut AnyObject = unsafe { msg_send![&*controller, updater] };
    if updater.is_null() {
        return Err("Sparkle's controller has no updater".into());
    }
    Ok(format!(
        "Sparkle ready; feed {}",
        info("SUFeedURL").unwrap_or_default()
    ))
}
