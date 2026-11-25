//! Windows native menu implementation (Win32 popup menus).

use std::{
    ffi::c_void,
    sync::{Arc, OnceLock},
};

use gpui::{Action, App, AssetSource, ImageFormat, Pixels, Point, Window};
use raw_window_handle::{HasWindowHandle, RawWindowHandle};
use windows::Win32::Foundation::{BOOL, GlobalFree, HANDLE, HWND, POINT};
use windows::Win32::Graphics::Gdi::{
    BI_RGB, BITMAPINFO, BITMAPINFOHEADER, ClientToScreen, CreateDIBSection, DIB_RGB_COLORS,
    DeleteObject, HBITMAP, HDC, HGDIOBJ,
};
use windows::Win32::Graphics::GdiPlus::{
    GdipCreateBitmapFromStream, GdipCreateHBITMAPFromBitmap, GdipDisposeImage,
    GdipGetImageThumbnail, GdiplusShutdown, GdiplusStartup, GdiplusStartupInput, GpBitmap, GpImage,
};
use windows::Win32::System::Com::StructuredStorage::CreateStreamOnHGlobal;
use windows::Win32::System::LibraryLoader::{
    GetProcAddress, LOAD_LIBRARY_SEARCH_SYSTEM32, LoadLibraryExW,
};
use windows::Win32::System::Memory::{GMEM_MOVEABLE, GlobalAlloc, GlobalLock, GlobalUnlock};
use windows::Win32::UI::WindowsAndMessaging::{
    AppendMenuW, CreatePopupMenu, DestroyMenu, HMENU, MENUITEMINFOW, MF_CHECKED, MF_GRAYED,
    MF_POPUP, MF_SEPARATOR, MF_STRING, MIIM_BITMAP, SetForegroundWindow, SetMenuItemInfoW,
    TPM_LEFTALIGN, TPM_NONOTIFY, TPM_RETURNCMD, TPM_TOPALIGN, TrackPopupMenuEx,
};
use windows::core::{PCSTR, PCWSTR};

use super::{NativeMenuItem, resolve_icon_image};

/// Side length (in **logical pixels**) menu item images are scaled to. The
/// physical bitmap size is this multiplied by the window's scale factor (see
/// [`show`]), so images stay sharp on the HiDPI displays.
const MENU_IMAGE_SIZE: u32 = 16;

/// Show a native popup menu and dispatch the selected item's action.
///
/// The Win32 tracking loop (`TrackPopupMenuEx`) blocks, so — like macOS — it is
/// run from a foreground task to avoid re-entering GPUI while it is borrowed.
pub(super) fn show(
    items: Vec<NativeMenuItem>,
    asset_source: Arc<dyn AssetSource>,
    position: Point<Pixels>,
    dark_mode: bool,
    window: &mut Window,
    cx: &mut App,
) {
    let Some(hwnd) = hwnd_ptr(window) else {
        return;
    };
    // `position` is logical pixels; Win32 wants physical pixels.
    let scale = window.scale_factor();
    let client_x = (f32::from(position.x) * scale).round() as i32;
    let client_y = (f32::from(position.y) * scale).round() as i32;
    // The menu draws item bitmaps at their native pixel size, so rasterize them
    // at the device pixel size to keep them sharp on HiDPI displays.
    let image_px = (MENU_IMAGE_SIZE as f32 * scale).round().max(1.0) as u32;
    // Inherent `Window::window_handle` (GPUI's `AnyWindowHandle`), not the
    // `raw_window_handle::HasWindowHandle` trait method in scope below.
    let handle = Window::window_handle(window);

    cx.spawn(async move |cx| {
        let Some(action) = run_menu(
            hwnd,
            &items,
            asset_source.as_ref(),
            client_x,
            client_y,
            image_px,
            dark_mode,
        ) else {
            return;
        };
        cx.update(move |app| {
            let _ = handle.update(app, move |_, window, app| {
                window.dispatch_action(action, app);
            });
        });
    })
    .detach();
}

/// Build the menu (recursively, including submenus), show it, and return the
/// selected item's action.
fn run_menu(
    hwnd: isize,
    items: &[NativeMenuItem],
    asset_source: &dyn AssetSource,
    client_x: i32,
    client_y: i32,
    image_px: u32,
    dark_mode: bool,
) -> Option<Box<dyn Action>> {
    let hwnd = HWND(hwnd as *mut c_void);

    // SAFETY: Win32 menu calls on a live window owned by the calling (main)
    // thread. The menu (and its submenus) is destroyed before returning.
    unsafe {
        // Start GDI+ so item images can be loaded into bitmaps. If it fails, the menu is still
        // built (images are skipped).
        let gdiplus = GdiplusSession::start();
        let mut actions: Vec<&Box<dyn Action>> = Vec::new();

        // Bitmaps attached to menu items must outlive the menu; freed below.
        let mut bitmaps: Vec<HBITMAP> = Vec::new();
        let menu = build_menu(items, asset_source, &mut actions, &mut bitmaps, image_px)?;

        let mut point = POINT {
            x: client_x,
            y: client_y,
        };
        let _ = ClientToScreen(hwnd, &mut point);
        // Required so the menu dismisses correctly when clicking elsewhere.
        let _ = SetForegroundWindow(hwnd);
        apply_menu_theme(hwnd, dark_mode);

        let flags = TPM_LEFTALIGN | TPM_TOPALIGN | TPM_RETURNCMD | TPM_NONOTIFY;
        let selected = TrackPopupMenuEx(menu, flags.0, point.x, point.y, hwnd, None);
        // Destroying the top menu also destroys its attached submenus.
        let _ = DestroyMenu(menu);

        // The menu no longer references the bitmaps, so they can be freed.
        for bitmap in &bitmaps {
            let _ = DeleteObject(HGDIOBJ(bitmap.0));
        }
        drop(gdiplus);

        // Ids are 1-based (0 means "no selection"); map back to `actions`.
        match selected.0 {
            id if id > 0 => actions
                .get((id - 1) as usize)
                .map(|action| action.boxed_clone()),
            _ => None,
        }
    }
}

/// Make Win32 popup menus follow the application's theme.
///
/// Windows does not expose a documented dark-mode API for `HMENU`. These
/// dynamically resolved uxtheme entry points are used by Windows itself and
/// degrade to the normal system menu when unavailable.
unsafe fn apply_menu_theme(hwnd: HWND, dark_mode: bool) {
    type AllowDarkModeForWindow = unsafe extern "system" fn(HWND, BOOL) -> BOOL;
    type SetPreferredAppMode = unsafe extern "system" fn(i32) -> i32;
    type FlushMenuThemes = unsafe extern "system" fn();

    static UXTHEME_MODULE: OnceLock<isize> = OnceLock::new();
    let module = *UXTHEME_MODULE.get_or_init(|| {
        // Restrict this system DLL to System32 to prevent application-directory DLL planting.
        unsafe {
            LoadLibraryExW(
                windows::core::w!("uxtheme.dll"),
                HANDLE::default(),
                LOAD_LIBRARY_SEARCH_SYSTEM32,
            )
        }
        .map(|module| module.0 as isize)
        .unwrap_or_default()
    });
    if module == 0 {
        return;
    }
    let module = windows::Win32::Foundation::HMODULE(module as *mut c_void);

    let allow_dark_mode = unsafe { GetProcAddress(module, PCSTR(133usize as *const u8)) };
    let set_preferred_mode = unsafe { GetProcAddress(module, PCSTR(135usize as *const u8)) };
    let flush_menu_themes = unsafe { GetProcAddress(module, PCSTR(136usize as *const u8)) };

    if let Some(function) = allow_dark_mode {
        let function: AllowDarkModeForWindow = unsafe { std::mem::transmute(function) };
        let _ = unsafe { function(hwnd, BOOL::from(dark_mode)) };
    }
    if let Some(function) = set_preferred_mode {
        let function: SetPreferredAppMode = unsafe { std::mem::transmute(function) };
        const FORCE_DARK: i32 = 2;
        const FORCE_LIGHT: i32 = 3;
        let _ = unsafe { function(if dark_mode { FORCE_DARK } else { FORCE_LIGHT }) };
    }
    if let Some(function) = flush_menu_themes {
        let function: FlushMenuThemes = unsafe { std::mem::transmute(function) };
        unsafe { function() };
    }
}

/// Recursively create an `HMENU`. Each actionable leaf gets a 1-based id equal
/// to its index in `actions` plus one, so the returned id maps back to its action.
///
/// Any bitmaps created for item images are pushed onto `bitmaps`; the caller
/// must free them after destroying the menu with `DeleteObject`. Item images
/// are sized to `image_px` (physical pixels).
///
/// # Safety
/// Win32 menu creation; the returned `HMENU` must be destroyed by the caller.
unsafe fn build_menu<'a>(
    items: &'a [NativeMenuItem],
    asset_source: &dyn AssetSource,
    actions: &mut Vec<&'a Box<dyn Action>>,
    bitmaps: &mut Vec<HBITMAP>,
    image_px: u32,
) -> Option<HMENU> {
    let menu = unsafe { CreatePopupMenu() }.ok()?;

    // 0-based position of the next item appended, used to attach bitmaps by position (separators
    // and submenus advance it too).
    let mut position: u32 = 0;
    for item in items {
        match item {
            NativeMenuItem::Separator => {
                let _ = unsafe { AppendMenuW(menu, MF_SEPARATOR, 0, PCWSTR::null()) };
                position += 1;
            }
            NativeMenuItem::Item {
                label,
                disabled,
                checked,
                icon,
                action,
            } => {
                let mut flags = MF_STRING;
                if *disabled {
                    flags |= MF_GRAYED;
                }
                if *checked {
                    flags |= MF_CHECKED;
                }
                let wide: Vec<u16> = label.encode_utf16().chain(std::iter::once(0)).collect();
                // Actionable, enabled items get an id; others use 0.
                let id = match action {
                    Some(action) if !*disabled => {
                        actions.push(action);
                        actions.len()
                    }
                    _ => 0,
                };
                let _ = unsafe { AppendMenuW(menu, flags, id, PCWSTR(wide.as_ptr())) };
                if let Some(icon) = icon {
                    if let Some(bitmap) = unsafe { load_hbitmap(icon, asset_source, image_px) } {
                        let info = MENUITEMINFOW {
                            cbSize: std::mem::size_of::<MENUITEMINFOW>() as u32,
                            fMask: MIIM_BITMAP,
                            hbmpItem: bitmap,
                            ..Default::default()
                        };
                        let _ = unsafe { SetMenuItemInfoW(menu, position, true, &info) };
                        bitmaps.push(bitmap);
                    }
                }
                position += 1;
            }
            NativeMenuItem::Submenu {
                label,
                disabled,
                items,
            } => {
                let Some(submenu) =
                    (unsafe { build_menu(items, asset_source, actions, bitmaps, image_px) })
                else {
                    continue;
                };
                let mut flags = MF_POPUP;
                if *disabled {
                    flags |= MF_GRAYED;
                }
                let wide: Vec<u16> = label.encode_utf16().chain(std::iter::once(0)).collect();
                // For MF_POPUP, the id parameter is the submenu handle.
                let _ =
                    unsafe { AppendMenuW(menu, flags, submenu.0 as usize, PCWSTR(wide.as_ptr())) };
                position += 1;
            }
        }
    }

    Some(menu)
}

/// RAII guard for a GDI+ session (`GdiplusStartup` / `GdiplusShutdown`).
///
/// Loading image files into bitmaps requires GDI+ to be initialized. A `None` token means startup
/// failed; image loading is then skipped gracefully.
struct GdiplusSession {
    token: usize,
}

impl GdiplusSession {
    /// Start GDI+. Returns a guard whose `Drop` calls `GdiplusShutdown`.
    unsafe fn start() -> Option<Self> {
        let input = GdiplusStartupInput {
            GdiplusVersion: 1,
            DebugEventCallback: 0,
            SuppressBackgroundThread: BOOL(0),
            SuppressExternalCodecs: BOOL(0),
        };

        let mut token: usize = 0;
        let status = unsafe { GdiplusStartup(&mut token, &input, std::ptr::null_mut()) };
        if status.0 == 0 {
            Some(Self { token })
        } else {
            None
        }
    }
}

impl Drop for GdiplusSession {
    fn drop(&mut self) {
        unsafe { GdiplusShutdown(self.token) };
    }
}

/// Load an image into an `HBITMAP`, scaled to `image_px` square so it
/// doesn't overflow the menu row.
///
/// SVG files are rasterized with `resvg` (see [`rasterize_svg`]); GDI+ has no
/// SVG codec. Every other format (PNG, JPEG, BMP, ...) is decoded by GDI+, which
/// must already be initialized (see [`GdiplusSession`]).
///
/// Returns `None` if the file can't be read or decoded. The returned bitmap
/// must be freed with `DeleteObject`.
///
/// # Safety
/// Calls GDI+ /GDI flat APIs; the returned handle is owned by the caller.
unsafe fn load_hbitmap(
    icon: &crate::Icon,
    asset_source: &dyn AssetSource,
    image_px: u32,
) -> Option<HBITMAP> {
    let image = resolve_icon_image(icon, asset_source)?;
    if image.bytes.is_empty() {
        return None;
    }

    if image.format == ImageFormat::Svg {
        return unsafe { rasterize_svg(&image.bytes, image_px) };
    }

    let stream = unsafe { stream_from_bytes(&image.bytes) }?;
    let mut gp_bitmap: *mut GpBitmap = std::ptr::null_mut();
    let status = unsafe { GdipCreateBitmapFromStream(&stream, &mut gp_bitmap) };
    if status.0 != 0 || gp_bitmap.is_null() {
        return None;
    }

    unsafe { thumbnail_hbitmap(gp_bitmap, image_px) }
}

unsafe fn thumbnail_hbitmap(gp_bitmap: *mut GpBitmap, image_px: u32) -> Option<HBITMAP> {
    // Scale to a menu icon sized thumbnail; GDI+ does not resize on display.
    let mut thumb: *mut GpImage = std::ptr::null_mut();
    let status = unsafe {
        GdipGetImageThumbnail(
            gp_bitmap.cast(),
            image_px,
            image_px,
            &mut thumb,
            0,
            std::ptr::null_mut(),
        )
    };

    unsafe { GdipDisposeImage(gp_bitmap.cast()) };
    if status.0 != 0 || thumb.is_null() {
        return None;
    }

    let mut hbitmap = HBITMAP::default();
    // ARGB background 0 (fully transparent) for the alpha conversion.
    let status = unsafe { GdipCreateHBITMAPFromBitmap(thumb.cast(), &mut hbitmap, 0) };

    unsafe { GdipDisposeImage(thumb) };

    if status.0 != 0 || hbitmap.is_invalid() {
        None
    } else {
        Some(hbitmap)
    }
}

unsafe fn stream_from_bytes(bytes: &[u8]) -> Option<windows::Win32::System::Com::IStream> {
    let hglobal = unsafe { GlobalAlloc(GMEM_MOVEABLE, bytes.len()) }.ok()?;
    let data = unsafe { GlobalLock(hglobal) };
    if data.is_null() {
        let _ = unsafe { GlobalFree(hglobal) };
        return None;
    }

    unsafe { std::ptr::copy_nonoverlapping(bytes.as_ptr(), data.cast::<u8>(), bytes.len()) };
    let _ = unsafe { GlobalUnlock(hglobal) };

    match unsafe { CreateStreamOnHGlobal(hglobal, BOOL(1)) } {
        Ok(stream) => Some(stream),
        Err(_) => {
            let _ = unsafe { GlobalFree(hglobal) };
            None
        }
    }
}

/// Extract the Win32 `HWND` (as an `isize`) from the window's raw handle.
fn hwnd_ptr(window: &Window) -> Option<isize> {
    let handle = HasWindowHandle::window_handle(window).ok()?;
    let RawWindowHandle::Win32(handle) = handle.as_raw() else {
        return None;
    };
    Some(handle.hwnd.get())
}

/// Rasterize SVG bytes into an `HBITMAP`, scaled to `image_px` square.
///
/// GDI+ has no SVG codec, so SVG data is rendered with `resvg` and wrapped in a
/// 32-bit DIB section. The SVG is scaled uniformly to fit the square and centered.
/// Returns `None` if the SVG can't be parsed. The returned bitmap must be freed
/// with `DeleteObject`.
///
/// # Safety
/// Creates a GDI DIB section; the returned handle is owned by the caller.
unsafe fn rasterize_svg(data: &[u8], image_px: u32) -> Option<HBITMAP> {
    use resvg::{tiny_skia, usvg};

    let tree = usvg::Tree::from_data(data, &usvg::Options::default()).ok()?;

    let size = image_px;
    let mut pixmap = tiny_skia::Pixmap::new(size, size)?;

    // Fit the SVG into square without distortion, then center it.
    let svg = tree.size();
    let scale = (size as f32 / svg.width()).min(size as f32 / svg.height());
    let tx = (size as f32 - svg.width() * scale) / 2.0;
    let ty = (size as f32 - svg.height() * scale) / 2.0;
    let transform = tiny_skia::Transform::from_scale(scale, scale).post_translate(tx, ty);

    resvg::render(&tree, transform, &mut pixmap.as_mut());

    // tiny-skia produces premultiplied RGBA; a 32 bit DIB is laid out RGBA, so
    // swap the red and blue channels in place. The alpha is already
    // premultiplied, which is what the menu's alpha blending expects.
    let mut pixels = pixmap.take();
    for px in pixels.chunks_exact_mut(4) {
        px.swap(0, 2)
    }

    unsafe { create_dib(&pixels, size, size) }
}

/// Wrap premultiplied-RGBA `pixels` (top-down, `width` x `height`) in a 32-bit
/// DIB section `HBITMAP`. Returns `None` if creation fails; the returned bitmap
/// must be freed with `DeleteObject`.
///
/// # Safety
/// Calls GDI flat APIs and copies `pixels` into the section's backing store,
/// which must be `width * height * 4` bytes.
unsafe fn create_dib(pixels: &[u8], width: u32, height: u32) -> Option<HBITMAP> {
    let info = BITMAPINFO {
        bmiHeader: BITMAPINFOHEADER {
            biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
            biWidth: width as i32,
            // Negative height selects a top-down DIB (origin at top-left), matching
            // tiny-skia's row order.
            biHeight: -(height as i32),
            biPlanes: 1,
            biBitCount: 32,
            biCompression: BI_RGB.0,
            ..Default::default()
        },
        ..Default::default()
    };

    let mut bits: *mut c_void = std::ptr::null_mut();
    // A null `HDC` is fine with `DIB_RGB_COLORS` (no palette to resolve).
    let hbitmap = unsafe {
        CreateDIBSection(
            HDC::default(),
            &info,
            DIB_RGB_COLORS,
            &mut bits,
            HANDLE::default(),
            0,
        )
    }
    .ok()?;

    if bits.is_null() {
        let _ = unsafe { DeleteObject(HGDIOBJ(hbitmap.0)) };
        return None;
    }

    unsafe { std::ptr::copy_nonoverlapping(pixels.as_ptr(), bits as *mut u8, pixels.len()) };
    Some(hbitmap)
}
