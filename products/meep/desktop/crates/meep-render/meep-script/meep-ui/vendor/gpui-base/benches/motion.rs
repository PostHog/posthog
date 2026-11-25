#[cfg(feature = "gpui-fast")]
extern crate gpui_fast as gpui;

use std::{
    alloc::{GlobalAlloc, Layout, System},
    hint::black_box,
    sync::atomic::{AtomicUsize, Ordering},
    time::Instant,
};

use gpui::{SpringConfig, SpringState};
use gpui_base::{Easing, Keyframe, Keyframes, Stagger, StaggerOrigin, Timing};

const BATCHES: usize = 31;
const WARMUP_BATCHES: usize = 5;
const ITERATIONS: usize = 200;

struct CountingAllocator;

static ALLOCATIONS: AtomicUsize = AtomicUsize::new(0);

// SAFETY: every operation is forwarded unchanged to the process System
// allocator; the counter has no bearing on allocation validity or lifetime.
unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        // SAFETY: `layout` is passed through from the GlobalAlloc caller.
        unsafe { System.alloc(layout) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        // SAFETY: `ptr` and `layout` are the same pair supplied by the caller.
        unsafe { System.dealloc(ptr, layout) }
    }

    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        // SAFETY: all arguments are passed through from the GlobalAlloc caller.
        unsafe { System.realloc(ptr, layout, new_size) }
    }
}

#[global_allocator]
static GLOBAL_ALLOCATOR: CountingAllocator = CountingAllocator;

fn main() {
    println!(
        "motion benchmark: {} {} release={} batches={} iterations={}",
        std::env::consts::OS,
        std::env::consts::ARCH,
        !cfg!(debug_assertions),
        BATCHES,
        ITERATIONS
    );

    let easing = Easing::Ease;
    let timing = Timing::new(std::time::Duration::from_millis(240)).ease(easing.clone());
    measure("1,000 scalar timing + easing samples", || {
        let mut sum = 0.0;
        for index in 0..1_000 {
            let elapsed = std::time::Duration::from_nanos((index * 211_003 % 240_000_000) as u64);
            sum += timing.sample(black_box(elapsed)).directed_progress;
        }
        black_box(sum);
    });

    for frame_count in [2, 8, 32] {
        let track = Keyframes::try_new((0..frame_count).map(|index| {
            let offset = index as f32 / (frame_count - 1) as f32;
            Keyframe::new(offset, offset * 100.0).ease(easing.clone())
        }))
        .unwrap();
        measure(
            &format!("1,000 keyframe samples ({frame_count} frames)"),
            || {
                let mut sum = 0.0;
                for index in 0..1_000 {
                    sum += track.sample(black_box((index % 997) as f32 / 996.0));
                }
                black_box(sum);
            },
        );
    }

    let spring = SpringConfig::new(438.65, 41.89, 1.0);
    measure("1,000 analytic spring integration samples", || {
        let mut state = SpringState {
            position: 0.0,
            velocity: 0.0,
        };
        for index in 0..1_000 {
            state = spring.step(state, black_box(1.0), (index % 3 + 1) as f32 / 240.0);
        }
        black_box(state);
    });

    let stagger = Stagger::new(std::time::Duration::from_millis(24), StaggerOrigin::Center);
    measure("1,000 stagger delay calculations", || {
        let mut sum = 0;
        for index in 0..1_000 {
            sum += stagger.delay(black_box(index % 32), 32).as_nanos();
        }
        black_box(sum);
    });
}

fn measure(name: &str, mut operation: impl FnMut()) {
    for _ in 0..WARMUP_BATCHES {
        for _ in 0..ITERATIONS {
            operation();
        }
    }

    let allocations_before = ALLOCATIONS.load(Ordering::Relaxed);
    for _ in 0..ITERATIONS {
        operation();
    }
    let steady_allocations = ALLOCATIONS.load(Ordering::Relaxed) - allocations_before;
    assert_eq!(
        steady_allocations, 0,
        "{name} allocated {steady_allocations} times in the steady sampling loop"
    );

    let mut samples = Vec::with_capacity(BATCHES);
    for _ in 0..BATCHES {
        let started = Instant::now();
        for _ in 0..ITERATIONS {
            operation();
        }
        samples.push(started.elapsed().as_secs_f64() * 1_000_000.0 / ITERATIONS as f64);
    }
    samples.sort_by(f64::total_cmp);
    let median = samples[BATCHES / 2];
    let p95 = samples[((BATCHES as f64 * 0.95).ceil() as usize - 1).min(BATCHES - 1)];
    let worst = samples[BATCHES - 1];
    println!("{name}: median={median:.3}us p95={p95:.3}us worst={worst:.3}us allocations=0");

    if name.starts_with("1,000 scalar") && median > 100.0 {
        panic!("Motion Core scalar sampling median {median:.3}us exceeds the 100us budget");
    }
}
