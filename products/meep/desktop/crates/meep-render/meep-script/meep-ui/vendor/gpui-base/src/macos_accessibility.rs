use std::{ffi::CString, ptr::null_mut};

use gpui::Window;
use objc2::{
    Message,
    encode::{Encode, EncodeArguments, EncodeReturn, Encoding},
    ffi::{class_addMethod, object_getClass},
    msg_send,
    runtime::{AnyClass, AnyObject, MethodImplementation, Sel},
    sel,
};
use objc2_app_kit::{NSView, NSWindow};
use objc2_foundation::NSPoint;
use raw_window_handle::{HasWindowHandle, RawWindowHandle};

pub fn install_window_hit_test_forwarder(window: &Window) {
    let Some(view) = ns_view(window) else {
        return;
    };
    let Some(window) = view.window() else {
        return;
    };

    unsafe {
        let class = object_getClass((&*window as *const NSWindow).cast::<AnyObject>());
        if !class.is_null() {
            add_method(
                class.cast_mut(),
                sel!(accessibilityHitTest:),
                hit_test_forwarder as extern "C" fn(_, _, _) -> _,
            );
        }
    }
}

extern "C" fn hit_test_forwarder(this: &NSWindow, _cmd: Sel, point: NSPoint) -> *mut AnyObject {
    this.contentView().map_or_else(null_mut, |view| unsafe {
        msg_send![&*view, accessibilityHitTest: point]
    })
}

fn ns_view(window: &Window) -> Option<&NSView> {
    let handle = HasWindowHandle::window_handle(window).ok()?;
    let RawWindowHandle::AppKit(handle) = handle.as_raw() else {
        return None;
    };
    unsafe { (handle.ns_view.as_ptr() as *const NSView).as_ref() }
}

unsafe fn add_method<T, F>(class: *mut AnyClass, sel: Sel, func: F)
where
    T: Message + ?Sized,
    F: MethodImplementation<Callee = T>,
{
    let encs = F::Arguments::ENCODINGS;
    debug_assert_eq!(
        count_args(sel),
        encs.len(),
        "selector {sel:?} argument count does not match method implementation"
    );

    let types = method_type_encoding(&F::Return::ENCODING_RETURN, encs);
    let success = unsafe { class_addMethod(class, sel, func.__imp(), types.as_ptr()) };
    let _ = success.as_bool();
}

fn count_args(sel: Sel) -> usize {
    sel.name().to_bytes().iter().filter(|&&c| c == b':').count()
}

fn method_type_encoding(ret: &Encoding, args: &[Encoding]) -> CString {
    let mut types = format!("{ret}{}{}", <*mut AnyObject>::ENCODING, Sel::ENCODING);
    for enc in args {
        use core::fmt::Write;
        write!(&mut types, "{enc}").unwrap();
    }
    CString::new(types).unwrap()
}
