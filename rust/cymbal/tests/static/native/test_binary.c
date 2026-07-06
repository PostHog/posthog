// Minimal test binary for ELF/DWARF symbolication testing.
// Built for x86_64-linux in both PIE and non-PIE flavors — see build.sh.

void inner_function(void) {
    // Line 6 - this should be symbolicated
    volatile int x = 42;
    (void)x;
}

void outer_function(void) {
    // Line 12
    inner_function();
}

int main(void) {
    // Line 17
    outer_function();
    return 0;
}
