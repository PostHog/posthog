#[cfg(target_env = "msvc")]
pub use std::alloc::System as DefaultAllocator;
#[cfg(not(target_env = "msvc"))]
pub use tikv_jemallocator::Jemalloc as DefaultAllocator;

pub mod pprof;
pub mod router;

// Use this macro as you would with used!() in common/alloc. Next, use the router module's
// `apply_pprof_routes` function to add the pprof routes to the axum::Router in your service.
// Some under-the-hood details on the allocation side of the profiling features here:
// https://www.polarsignals.com/blog/posts/2023/12/20/rust-memory-profiling
#[macro_export]
macro_rules! used_with_profiling {
    () => {
        #[global_allocator]
        static GLOBAL: $crate::DefaultAllocator = $crate::DefaultAllocator;

        #[allow(non_upper_case_globals)]
        #[export_name = "malloc_conf"]
        static malloc_conf: &[u8] = b"prof:true,prof_active:true,lg_prof_sample:19\0";
    };
}
