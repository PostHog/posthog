// Test binary with inlined functions for DWARF expansion testing

__attribute__((always_inline))
static inline void inlined_leaf(void) {
    // Line 4 - this is always inlined into its caller
    volatile int x = 99;
    (void)x;
}

void inner_function(void) {
    // Line 10
    inlined_leaf();    // Line 11 - inlined_leaf gets inlined here
}

void outer_function(void) {
    // Line 15
    inner_function();
}

int main(void) {
    // Line 20
    outer_function();
    return 0;
}
