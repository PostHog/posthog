//! Pixel layout conversions for the image-scrub sidecar: its model input tensors and zxing's RGBA
//! frame.
//!
//! Every kernel writes into a destination that the caller allocated, and allocates nothing itself,
//! so the Node binding can pass typed arrays that it borrowed in place and no pixel crosses the
//! boundary as a copy.

use std::fmt;

/// The source channel that each output plane takes, in plane order.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PlaneOrder {
    Rgb,
    Bgr,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LayoutError {
    PartialPixel { rgb_len: usize },
    DestinationLength { expected: usize, actual: usize },
}

impl fmt::Display for LayoutError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            LayoutError::PartialPixel { rgb_len } => {
                write!(f, "rgb length {rgb_len} is not a whole number of pixels")
            }
            LayoutError::DestinationLength { expected, actual } => {
                write!(f, "destination length is {actual}, expected {expected}")
            }
        }
    }
}

/// Interleaved RGB bytes to channel-major planes with the byte values unchanged (0 to 255).
pub fn rgb_to_chw(rgb: &[u8], chw: &mut [f32], order: PlaneOrder) -> Result<(), LayoutError> {
    let pixels = pixel_count(rgb, chw.len(), 3)?;
    match order {
        PlaneOrder::Rgb => fill_planes::<0, 1, 2>(rgb, chw, pixels, |_, value| f32::from(value)),
        PlaneOrder::Bgr => fill_planes::<2, 1, 0>(rgb, chw, pixels, |_, value| f32::from(value)),
    }
    Ok(())
}

/// Interleaved RGB bytes to channel-major planes of `(value / 255 - mean) / std`, with `mean` and
/// `std` given in plane order.
pub fn rgb_to_normalized_chw(
    rgb: &[u8],
    chw: &mut [f32],
    order: PlaneOrder,
    mean: [f64; 3],
    std: [f64; 3],
) -> Result<(), LayoutError> {
    let pixels = pixel_count(rgb, chw.len(), 3)?;
    let tables = normalization_tables(mean, std);
    let normalize = |plane: usize, value: u8| tables[plane][usize::from(value)];
    match order {
        PlaneOrder::Rgb => fill_planes::<0, 1, 2>(rgb, chw, pixels, normalize),
        PlaneOrder::Bgr => fill_planes::<2, 1, 0>(rgb, chw, pixels, normalize),
    }
    Ok(())
}

/// Interleaved RGB bytes to interleaved RGBA bytes with every pixel opaque.
pub fn rgb_to_rgba(rgb: &[u8], rgba: &mut [u8]) -> Result<(), LayoutError> {
    pixel_count(rgb, rgba.len(), 4)?;
    for (pixel, out) in rgb.chunks_exact(3).zip(rgba.chunks_exact_mut(4)) {
        out[0] = pixel[0];
        out[1] = pixel[1];
        out[2] = pixel[2];
        out[3] = u8::MAX;
    }
    Ok(())
}

fn pixel_count(
    rgb: &[u8],
    destination_len: usize,
    destination_values_per_pixel: usize,
) -> Result<usize, LayoutError> {
    if !rgb.len().is_multiple_of(3) {
        return Err(LayoutError::PartialPixel { rgb_len: rgb.len() });
    }
    let pixels = rgb.len() / 3;
    let expected = pixels * destination_values_per_pixel;
    if destination_len != expected {
        return Err(LayoutError::DestinationLength {
            expected,
            actual: destination_len,
        });
    }
    Ok(pixels)
}

// The source channels are const parameters so that LLVM sees a fixed stride-3 access pattern, which
// it vectorizes (with `ld3` on aarch64) instead of emitting one scalar load per byte.
#[inline(always)]
fn fill_planes<
    const FIRST_CHANNEL: usize,
    const SECOND_CHANNEL: usize,
    const THIRD_CHANNEL: usize,
>(
    rgb: &[u8],
    chw: &mut [f32],
    pixels: usize,
    convert: impl Fn(usize, u8) -> f32,
) {
    let (first_plane, rest) = chw.split_at_mut(pixels);
    let (second_plane, third_plane) = rest.split_at_mut(pixels);
    let planes = first_plane.iter_mut().zip(second_plane).zip(third_plane);
    for (pixel, ((first, second), third)) in rgb.chunks_exact(3).zip(planes) {
        *first = convert(0, pixel[FIRST_CHANNEL]);
        *second = convert(1, pixel[SECOND_CHANNEL]);
        *third = convert(2, pixel[THIRD_CHANNEL]);
    }
}

// Each entry evaluates the expression in f64 and rounds once to the nearest-even f32, which is what
// JS does when it computes the expression and stores it into a Float32Array. The sidecar needs its
// model inputs to match that bit for bit, and f32 arithmetic would differ in the last bit for some
// inputs.
fn normalization_tables(mean: [f64; 3], std: [f64; 3]) -> [[f32; 256]; 3] {
    let mut tables = [[0.0; 256]; 3];
    for value in 0..=u8::MAX {
        let scaled = f64::from(value) / 255.0;
        for ((table, mean), std) in tables.iter_mut().zip(mean).zip(std) {
            table[usize::from(value)] = ((scaled - mean) / std) as f32;
        }
    }
    tables
}

#[cfg(test)]
mod tests {
    use std::alloc::{GlobalAlloc, Layout, System};
    use std::cell::Cell;

    use super::*;

    struct CountingAllocator;

    thread_local! {
        static ALLOCATIONS: Cell<usize> = const { Cell::new(0) };
    }

    unsafe impl GlobalAlloc for CountingAllocator {
        unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
            ALLOCATIONS.with(|count| count.set(count.get() + 1));
            System.alloc(layout)
        }

        unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
            System.dealloc(ptr, layout)
        }
    }

    #[global_allocator]
    static ALLOCATOR: CountingAllocator = CountingAllocator;

    fn allocations_during(run: impl FnOnce()) -> usize {
        let before = ALLOCATIONS.with(Cell::get);
        run();
        ALLOCATIONS.with(Cell::get) - before
    }

    #[test]
    fn kernels_write_in_place_without_allocating() {
        let pixels = 1001;
        let rgb: Vec<u8> = (0..pixels * 3).map(|i| (i * 7 % 256) as u8).collect();
        let mut chw = vec![0.0f32; pixels * 3];
        let mut rgba = vec![0u8; pixels * 4];

        let allocations = allocations_during(|| {
            rgb_to_chw(&rgb, &mut chw, PlaneOrder::Bgr).unwrap();
            rgb_to_normalized_chw(
                &rgb,
                &mut chw,
                PlaneOrder::Bgr,
                [0.485, 0.456, 0.406],
                [0.229, 0.224, 0.225],
            )
            .unwrap();
            rgb_to_rgba(&rgb, &mut rgba).unwrap();
        });

        assert_eq!(allocations, 0);
    }
}
