use regex::Regex;

#[tokio::main]
async fn main() {
    let composed_map = sourcemap::decode_slice(
        include_str!("../../tests/static/hermes/composed_example.map").as_bytes(),
    )
    .unwrap();
    let raw_stack = include_str!("../../tests/static/hermes/raw_stack.txt");

    let frame_regex = Regex::new(r"at\s+(\S+)\s+\(address at\s+[^:]+:(\d+):(\d+)\)").unwrap();
    let expected_names = [
        "c",
        "b",
        "a",
        "loadModuleImplementation",
        "guardedLoadModule",
        "metroRequire",
        "global",
    ];

    for (captures, expected) in frame_regex
        .captures_iter(raw_stack)
        .zip(expected_names.iter())
    {
        let line: u32 = captures[2].parse().unwrap();
        let col: u32 = captures[3].parse().unwrap();

        composed_map.lookup_token(line - 1, col).unwrap();
        let resolved = composed_map
            .get_original_function_name(line - 1, col, Some(&captures[1]), None)
            .unwrap_or(&captures[1]);

        assert_eq!(resolved, *expected);
    }
}
