// Android NDK-shaped fixture: a JNI entry point calling into mangled C++
// with an inlined leaf, compiled as an aarch64-linux-android shared object.
// Mirrors what an NDK crash reports: frames inside an APK-packaged .so.
// Freestanding (no bionic): the binary is never executed by tests; it only
// needs valid DWARF, Itanium-mangled symbols, and a GNU build id.
using i64 = long long;

namespace engine {

__attribute__((always_inline)) inline i64 inlined_leaf(i64 v) {
    volatile i64 x = v * 3;
    return x + 1;
}

__attribute__((noinline)) i64 process_frame(i64 v) {
    volatile i64 acc = 0;
    for (int i = 0; i < 4; i++) {
        acc += inlined_leaf(v + i);
    }
    return acc;
}

} // namespace engine

extern "C" __attribute__((noinline)) i64
Java_com_example_app_MainActivity_nativeRender(void*, void*, i64 v) {
    return engine::process_frame(v) + 7;
}
