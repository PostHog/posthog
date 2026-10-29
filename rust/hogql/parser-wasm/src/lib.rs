//! WASM interface to the HogQL parser for `services/hogql-language-service`. The JSON matches what
//! `hogql_parser_rs.parse_*_json` returns to Python, including the error envelope. Buffers are boxed slices so that
//! `hogql_free` can rebuild the exact allocation from the pointer and length alone.

#[no_mangle]
pub extern "C" fn hogql_alloc(len: usize) -> *mut u8 {
    Box::into_raw(vec![0u8; len].into_boxed_slice()).cast::<u8>()
}

/// # Safety
///
/// `pointer` and `len` must come from one `hogql_alloc` call or one `hogql_parse_*` result, and the host must free
/// each buffer once.
#[no_mangle]
pub unsafe extern "C" fn hogql_free(pointer: *mut u8, len: usize) {
    drop(Box::from_raw(std::ptr::slice_from_raw_parts_mut(
        pointer, len,
    )));
}

/// The result packs the JSON buffer as `(pointer << 32) | length`, because WASM addresses are 32-bit and one return
/// value avoids a second exported call.
///
/// # Safety
///
/// `pointer` and `len` must describe a `hogql_alloc` buffer that holds valid UTF-8.
#[no_mangle]
pub unsafe extern "C" fn hogql_parse_select(pointer: *const u8, len: usize) -> u64 {
    let query = std::str::from_utf8_unchecked(std::slice::from_raw_parts(pointer, len));
    into_host_buffer(hogql_parser_rs::json::parse_select(query))
}

fn into_host_buffer(json: String) -> u64 {
    let bytes = json.into_bytes().into_boxed_slice();
    let len = bytes.len() as u64;
    let pointer = Box::into_raw(bytes).cast::<u8>() as usize as u64;
    (pointer << 32) | len
}
