#[tokio::main]
async fn main() {
    let metro_map = include_str!("../../tests/static/hermes/metro_example.map");
    let hermes_map = include_str!("../../tests/static/hermes/hermes_example.map");
    let composed_map = include_str!("../../tests/static/hermes/composed_example.map");
    let raw_stack = include_str!("../../tests/static/hermes/raw_stack.txt");
    let final_stack = include_str!("../../tests/static/hermes/final_stack.txt");

    let metro_map = sourcemap::decode_slice(metro_map.as_bytes()).unwrap();
    let hermes_map = sourcemap::decode_slice(hermes_map.as_bytes()).unwrap();
    let composed_map = sourcemap::decode_slice(composed_map.as_bytes()).unwrap();

    let token = composed_map.lookup_token(0, 8277).unwrap();
    println!("composed token: {:?}", token);

    // Try the two-hop method
    let hermes_token = hermes_map.lookup_token(0, 8277).unwrap();
    println!("hermes token: {:?}", hermes_token);
    let metro_token = metro_map
        .lookup_token(hermes_token.get_src_line(), hermes_token.get_src_col())
        .unwrap();
    println!("metro token: {:?}", metro_token);

    println!(
        "original function name composed: {:?}",
        composed_map.get_original_function_name(0, 8228, None, None)
    )
}
