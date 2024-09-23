// src/lexer.rs
use std::iter::Peekable;
use std::str::Chars;

#[derive(Debug, Clone, PartialEq, serde::Serialize)]
pub enum Token {
    Select,
    From,
    Where,
    And,
    Or,
    Identifier(String),
    Operator(String),
    Literal(String),
    Comma,
    Semicolon,
    Asterisk,
    LeftParen,
    RightParen,
    EOF,
}

pub struct Lexer<'a> {
    input: Peekable<Chars<'a>>,
}

impl<'a> Lexer<'a> {
    pub fn new(input: &'a str) -> Self {
        Lexer {
            input: input.chars().peekable(),
        }
    }

    fn next_char(&mut self) -> Option<char> {
        self.input.next()
    }

    fn peek_char(&mut self) -> Option<&char> {
        self.input.peek()
    }

    fn skip_whitespace(&mut self) {
        while matches!(self.peek_char(), Some(c) if c.is_whitespace()) {
            self.next_char();
        }
    }

    fn lex_identifier(&mut self, first_char: char) -> String {
        let mut ident = first_char.to_string();
        while matches!(self.peek_char(), Some(c) if c.is_alphanumeric() || *c == '_') {
            ident.push(self.next_char().unwrap());
        }
        ident
    }

    fn lex_number(&mut self, first_char: char) -> String {
        let mut number = first_char.to_string();
        while matches!(self.peek_char(), Some(c) if c.is_numeric() || *c == '.') {
            number.push(self.next_char().unwrap());
        }
        number
    }

    fn lex_string(&mut self) -> String {
        let mut string = String::new();
        // Do not skip the opening quote here
        while let Some(c) = self.next_char() {
            if c == '\'' {
                break;
            }
            string.push(c);
        }
        string
    }

    pub fn get_next_token(&mut self) -> Token {
        self.skip_whitespace();
        if let Some(c) = self.next_char() {
            match c {
                ',' => Token::Comma,
                ';' => Token::Semicolon,
                '*' => Token::Asterisk,
                '(' => Token::LeftParen,
                ')' => Token::RightParen,
                '=' | '>' | '<' | '!' => {
                    let mut op = c.to_string();
                    if let Some(next_c) = self.peek_char() {
                        if *next_c == '=' || (c == '<' && *next_c == '>') || (c == '!' && *next_c == '=') {
                            op.push(*next_c);
                            self.next_char();
                        }
                    }
                    Token::Operator(op)
                }
                '\'' => {
                    Token::Literal(self.lex_string())
                },
                c if c.is_alphabetic() || c == '_' => {
                    let ident = self.lex_identifier(c);
                    match ident.to_uppercase().as_str() {
                        "SELECT" => Token::Select,
                        "FROM" => Token::From,
                        "WHERE" => Token::Where,
                        "AND" => Token::And,
                        "OR" => Token::Or,
                        _ => Token::Identifier(ident),
                    }
                }
                c if c.is_numeric() => Token::Literal(self.lex_number(c)),
                _ => panic!("Unknown character: {}", c),
            }
        } else {
            Token::EOF
        }
    }
}
