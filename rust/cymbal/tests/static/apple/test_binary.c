// Minimal test binary for dSYM generation
// This creates a simple executable with debug symbols

void inner_function(void) {
    // Line 5 - this should be symbolicated
    volatile int x = 42;
    (void)x;
}

void outer_function(void) {
    // Line 11
    inner_function();
}

int main(void) {
    // Line 16
    outer_function();
    return 0;
}
