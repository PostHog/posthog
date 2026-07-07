// Minimal Rust test binary for ELF/DWARF symbolication testing, exercising
// rustc symbol mangling (demangled server-side via symbolic). See build.sh.

mod checkout {
    pub mod payment {
        #[inline(never)]
        pub fn charge() {
            // Line 9 - this should be symbolicated and demangled
            let x = std::hint::black_box(42);
            let _ = x;
        }
    }
}

fn main() {
    // Line 17
    checkout::payment::charge();
}
