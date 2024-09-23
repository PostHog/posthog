// src/lib.rs
mod lexer;
mod parser;

use lexer::Lexer;
use parser::Parser;

#[cfg(target_arch = "wasm32")]
use wasm_bindgen::prelude::*;

#[cfg_attr(target_arch = "wasm32", wasm_bindgen)]
pub fn parse_query(input: &str) -> serde_json::Value {
    let lexer = Lexer::new(input);
    let mut parser = Parser::new(lexer);

    let ast = parser.parse();
    serde_json::to_value(&ast).unwrap()
}
