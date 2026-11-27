use super::*;
use image::{AnimationDecoder, codecs::webp::WebPDecoder};
use std::{
    io::Cursor,
    sync::{Arc, LazyLock},
};

struct PuppetArt {
    chicken: Arc<RenderImage>,
    backlight: Arc<RenderImage>,
    eyes: [Arc<RenderImage>; 9],
    inspecting: Arc<RenderImage>,
    cable: Arc<RenderImage>,
}

fn decode(bytes: &[u8]) -> Arc<RenderImage> {
    let decoder = WebPDecoder::new(Cursor::new(bytes)).expect("embedded puppet WebP");
    let frames = decoder
        .into_frames()
        .collect_frames()
        .expect("embedded puppet frames");
    render_image(frames)
}

fn render_image(mut frames: Vec<image::Frame>) -> Arc<RenderImage> {
    for frame in &mut frames {
        for pixel in frame.buffer_mut().pixels_mut() {
            pixel.0.swap(0, 2);
        }
    }
    Arc::new(RenderImage::new(frames))
}

macro_rules! art {
    ($name:literal) => {
        decode(include_bytes!(concat!("../assets/puppet/", $name, ".webp")))
    };
}

static ART: LazyLock<PuppetArt> = LazyLock::new(|| PuppetArt {
    chicken: art!("chicken"),
    backlight: render_image(vec![image::Frame::new(
        image::load_from_memory_with_format(
            include_bytes!("../assets/puppet/backlight.png"),
            image::ImageFormat::Png,
        )
        .expect("embedded puppet backlight")
        .into_rgba8(),
    )]),
    eyes: [
        art!("eyes-0"),
        art!("eyes-1"),
        art!("eyes-2"),
        art!("eyes-3"),
        art!("eyes-4"),
        art!("eyes-5"),
        art!("eyes-6"),
        art!("eyes-7"),
        art!("eyes-8"),
    ],
    inspecting: art!("inspect"),
    cable: art!("cable"),
});

pub fn preload() {
    LazyLock::force(&ART);
}

fn picture(id: &'static str, image: &Arc<RenderImage>, size: f32) -> Div {
    div()
        .relative()
        .flex_none()
        .size(px(size))
        .when(ui::theme::is_dark(), |el| {
            let spread = size * 0.22;
            el.child(
                div()
                    .absolute()
                    .overflow_hidden()
                    .left(px(-spread))
                    .top(px(-spread))
                    .size(px(size + 2. * spread))
                    .child(
                        img(ART.backlight.clone())
                            .absolute()
                            .left(px(-2.))
                            .top(px(-2.))
                            .size(px(size + 2. * spread + 4.))
                            .opacity(if size < 48. { 0.6 } else { 1. }),
                    ),
            )
        })
        .child(
            img(image.clone())
                .id(id)
                .size_full()
                .object_fit(ObjectFit::Contain),
        )
}

pub fn opening(gaze: usize, size: f32) -> Div {
    let scale = size / 650.;
    picture("rubber-chicken", &ART.chicken, size).child(
        img(ART.eyes[gaze].clone())
            .id("opening-eyes")
            .absolute()
            .left(px(215. * scale))
            .top(px(140. * scale))
            .w(px(220. * scale))
            .h(px(83. * scale)),
    )
}

pub fn inspecting() -> Div {
    picture("inspecting-puppet", &ART.inspecting, 96.)
}

pub fn connection_error(size: f32) -> Div {
    picture("cable-puppet", &ART.cable, size)
}
