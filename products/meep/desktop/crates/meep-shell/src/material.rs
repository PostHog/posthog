//! Native AppKit Liquid Glass underneath the existing GPUI Metal renderer.
//! Uses public macOS 26 APIs. The bridge follows GPUI's measured bounds and
//! never owns input; older systems and Reduce Transparency get an opaque fill.
//! Underlay hosting approach informed by Rhein-Industries/gpui-macos (MIT/Apache-2.0).
use gpui_kit::*;

/// A glass material element positioned behind the window content.
#[derive(IntoElement)]
pub struct Material {
    id: ElementId,
    base: Stateful<Div>,
    radius: Pixels,
}
/// Create a glass element with a stable GPUI identifier.
pub fn glass(id: impl Into<ElementId>) -> Material {
    let id = id.into();
    Material {
        base: div().id(id.clone()).relative(),
        id,
        radius: px(0.),
    }
}
impl Material {
    /// Round the material's corners to the supplied radius.
    pub fn radius(mut self, radius: Pixels) -> Self {
        self.radius = radius;
        self.base = self.base.rounded(radius);
        self
    }
}
impl Styled for Material {
    fn style(&mut self) -> &mut StyleRefinement {
        self.base.style()
    }
}
impl ParentElement for Material {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.base.extend(elements)
    }
}
impl InteractiveElement for Material {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}
impl StatefulInteractiveElement for Material {}
impl RenderOnce for Material {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        #[cfg(target_family = "wasm")]
        {
            let _ = (window, cx);
            let id = format!("{:?}", self.id);
            let radius = self.radius;
            self.base.child(
                canvas(
                    |bounds, window, _| (bounds, bounds.intersect(&window.content_mask().bounds)),
                    move |_, (bounds, visible), _, _| {
                        web::place(
                            &id,
                            f32::from(bounds.origin.x),
                            f32::from(bounds.origin.y),
                            f32::from(bounds.size.width),
                            f32::from(bounds.size.height),
                            f32::from(visible.origin.x),
                            f32::from(visible.origin.y),
                            f32::from(visible.size.width),
                            f32::from(visible.size.height),
                            f32::from(radius),
                        );
                    },
                )
                .absolute()
                .inset_0(),
            )
        }
        #[cfg(target_os = "macos")]
        if native::available(window) {
            let host = window.use_keyed_state((self.id, "appkit-glass"), cx, |window, _| {
                native::Host::new(window)
            });
            if host.read(cx).is_some() {
                let radius = self.radius;
                return self.base.child(
                    canvas(
                        |bounds, window, _| bounds.intersect(&window.content_mask().bounds),
                        move |bounds, visible, window, cx| {
                            if let Some(host) = host.read(cx) {
                                host.place(bounds, visible, radius, window);
                            }
                        },
                    )
                    .absolute()
                    .inset_0(),
                );
            }
        }
        #[cfg(not(target_family = "wasm"))]
        self.base.bg(rgb(meep_ui::components::theme::get(6)))
    }
}

#[cfg(target_os = "macos")]
mod native {
    use super::*;
    use objc2::{
        MainThreadMarker, MainThreadOnly, define_class, msg_send, rc::Retained, runtime::AnyClass,
    };
    use objc2_app_kit::{
        NSAppearance, NSAppearanceCustomization, NSAppearanceNameAqua, NSAppearanceNameDarkAqua,
        NSGlassEffectView, NSGlassEffectViewStyle, NSView, NSWindowOrderingMode, NSWorkspace,
    };
    use objc2_foundation::{NSObjectProtocol, NSPoint, NSRect, NSSize};
    use raw_window_handle::{HasWindowHandle, RawWindowHandle};
    use std::cell::Cell;

    define_class!(
        // SAFETY: NSView has no additional subclass invariants. All methods and
        // lifecycle operations stay on GPUI's AppKit main thread.
        #[unsafe(super=NSView)]
        #[name="ViewPassiveGlassHost"]
        #[thread_kind=MainThreadOnly]
        struct PassiveHost;
        unsafe impl NSObjectProtocol for PassiveHost {}
        impl PassiveHost {
            #[unsafe(method(isFlipped))]
            fn flipped(&self)->bool{true}
            #[unsafe(method_id(hitTest:))]
            fn hit_test(&self,_point:NSPoint)->Option<Retained<NSView>>{None}
        }
    );
    fn renderer(window: &Window) -> Option<Retained<NSView>> {
        MainThreadMarker::new()?;
        let handle = HasWindowHandle::window_handle(window).ok()?;
        let RawWindowHandle::AppKit(handle) = handle.as_raw() else {
            return None;
        };
        // SAFETY: The borrowed live GPUI Window supplies a valid NSView pointer.
        unsafe { Retained::retain(handle.ns_view.as_ptr().cast::<NSView>()) }
    }
    pub fn available(window: &Window) -> bool {
        let Some(marker) = MainThreadMarker::new() else {
            return false;
        };
        if AnyClass::get(c"NSGlassEffectView").is_none() {
            return false;
        }
        if NSWorkspace::sharedWorkspace().accessibilityDisplayShouldReduceTransparency() {
            return false;
        }
        let _ = marker;
        renderer(window).is_some_and(|view| unsafe { view.superview() }.is_some())
    }
    pub struct Host {
        host: Retained<PassiveHost>,
        glass: Retained<NSGlassEffectView>,
        previous: Cell<Option<(NSRect, NSRect, f64)>>,
    }
    impl Host {
        pub fn new(window: &Window) -> Option<Self> {
            let marker = MainThreadMarker::new()?;
            if !available(window) {
                return None;
            }
            let renderer = renderer(window)?;
            // SAFETY: AppKit hierarchy is accessed only on its main thread.
            let parent = unsafe { renderer.superview() }?;
            let host: Retained<PassiveHost> =
                unsafe { msg_send![PassiveHost::alloc(marker),initWithFrame:NSRect::ZERO] };
            host.setClipsToBounds(true);
            host.setHidden(true);
            let glass = NSGlassEffectView::new(marker);
            glass.setContentView(Some(&NSView::new(marker)));
            glass.setStyle(NSGlassEffectViewStyle::Regular);
            if let Some(appearance) = NSAppearance::appearanceNamed(unsafe { NSAppearanceNameAqua })
            {
                glass.setAppearance(Some(&appearance));
            }
            eprintln!("Native Liquid Glass surface attached (NSGlassEffectView)");
            host.addSubview(&glass);
            parent.addSubview_positioned_relativeTo(
                &host,
                NSWindowOrderingMode::Below,
                Some(&renderer),
            );
            Some(Self {
                host,
                glass,
                previous: Cell::new(None),
            })
        }
        pub fn place(
            &self,
            bounds: Bounds<Pixels>,
            visible: Bounds<Pixels>,
            radius: Pixels,
            window: &Window,
        ) {
            let appearance_name = if meep_ui::components::theme::is_dark() {
                unsafe { NSAppearanceNameDarkAqua }
            } else {
                unsafe { NSAppearanceNameAqua }
            };
            if let Some(appearance) = NSAppearance::appearanceNamed(appearance_name) {
                self.glass.setAppearance(Some(&appearance));
            }
            if visible.size.width <= px(0.) || visible.size.height <= px(0.) {
                self.host.setHidden(true);
                return;
            }
            let Some(renderer) = renderer(window) else {
                return;
            };
            let Some(parent) = (unsafe { renderer.superview() }) else {
                return;
            };
            let rect = |bounds: Bounds<Pixels>| {
                NSRect::new(
                    NSPoint::new(
                        f32::from(bounds.origin.x) as f64,
                        f32::from(bounds.origin.y) as f64,
                    ),
                    NSSize::new(
                        f32::from(bounds.size.width) as f64,
                        f32::from(bounds.size.height) as f64,
                    ),
                )
            };
            let mut frame = rect(visible);
            if !parent.isFlipped() {
                frame.origin.y = parent.bounds().size.height - frame.origin.y - frame.size.height;
            }
            let glass_frame = NSRect::new(
                NSPoint::new(
                    f32::from(bounds.origin.x - visible.origin.x) as f64,
                    f32::from(bounds.origin.y - visible.origin.y) as f64,
                ),
                NSSize::new(
                    f32::from(bounds.size.width) as f64,
                    f32::from(bounds.size.height) as f64,
                ),
            );
            let radius = (f32::from(radius) as f64)
                .max(0.)
                .min(glass_frame.size.width / 2.)
                .min(glass_frame.size.height / 2.);
            if self.previous.get() != Some((frame, glass_frame, radius)) {
                self.host.setFrame(frame);
                self.glass.setFrame(glass_frame);
                self.glass.setCornerRadius(radius);
                self.previous.set(Some((frame, glass_frame, radius)));
            }
            self.host.setHidden(false);
        }
    }
    impl Drop for Host {
        fn drop(&mut self) {
            if MainThreadMarker::new().is_some() {
                self.host.removeFromSuperview();
            }
        }
    }
}

#[cfg(target_family = "wasm")]
mod web {
    use wasm_bindgen::prelude::*;
    #[wasm_bindgen]
    extern "C" {
        #[wasm_bindgen(js_name = viewPlaceMaterial)]
        pub fn place(
            id: &str,
            x: f32,
            y: f32,
            width: f32,
            height: f32,
            clip_x: f32,
            clip_y: f32,
            clip_width: f32,
            clip_height: f32,
            radius: f32,
        );
    }
}
