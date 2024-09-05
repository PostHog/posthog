#[cfg(target_env = "msvc")]
pub use std::alloc::System as DefaultAllocator;
#[cfg(not(target_env = "msvc"))]
pub use tikv_jemallocator::Jemalloc as DefaultAllocator;

#[macro_export]
macro_rules! used {
    () => {
        #[global_allocator]
        static GLOBAL: $crate::DefaultAllocator = $crate::DefaultAllocator;
    };
}
