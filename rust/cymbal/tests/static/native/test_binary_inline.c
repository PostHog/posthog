// Test binary with inlined functions for DWARF inline expansion testing.

__attribute__((always_inline))
static inline void inlined_leaf(void) {
    // Line 5 - this is always inlined into its caller
    volatile int x = 99;
    (void)x;
}

__attribute__((always_inline))
inline void inner_function(void) {
    // Line 12
    inlined_leaf();    // inlined_leaf gets inlined here
}

void outer_function(void) {
    // Line 17
    inner_function();  // both layers get inlined here
}

int main(void) {
    // Line 22
    outer_function();
    return 0;
}
