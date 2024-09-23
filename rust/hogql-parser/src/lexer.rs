// src/lexer.rs
use std::iter::Peekable;
use std::str::Chars;

#[derive(Debug, Clone, PartialEq, serde::Serialize)]
pub enum Token {
    // Keywords
    All,
    And,
    Anti,
    Any,
    Array,
    As,
    Ascending,
    Asc,
    Asof,
    Between,
    Both,
    By,
    Case,
    Cast,
    Catch,
    Cohort,
    Collate,
    Cross,
    Cube,
    Current,
    Date,
    Day,
    Desc,
    Descending,
    Distinct,
    Else,
    End,
    Extract,
    Final,
    Finally,
    First,
    Fn,
    Following,
    For,
    From,
    Full,
    Fun,
    Group,
    Having,
    Hour,
//     Id,
    If,
    Ilike,
    In,
    Inf,
    Inner,
    Interval,
    Is,
    Join,
    Key,
    Last,
    Leading,
    Left,
    Let,
    Like,
    Limit,
    Minute,
    Month,
    NanSql,
    Not,
    NullSql,
    Nulls,
    Offset,
    On,
    Or,
    Order,
    Outer,
    Over,
    Partition,
    Preceding,
    Prewhere,
    Quarter,
    Range,
    Return,
    Right,
    Rollup,
    Row,
    Rows,
    Sample,
    Second,
    Select,
    Semi,
    Settings,
    Substring,
    Then,
    Throw,
    Ties,
    Timestamp,
    To,
    Top,
    Totals,
    Trailing,
    Trim,
    Truncate,
    Try,
    Unbounded,
    Union,
    Using,
    Week,
    When,
    Where,
    While,
    Window,
    With,
    Year,

    // Identifiers and Literals
    Identifier(String),
    StringLiteral(String),
    NumberLiteral(String),

    // Operators
    Operator(String),

    // Symbols
    Comma,
    Semicolon,
    Asterisk,
    LParen,
    RParen,
    LBracket,
    RBracket,
    LBrace,
    RBrace,
    Dot,
    Plus,
    Dash,
    Slash,
    Percent,
    Colon,
    Query,
    EqSingle,
    EqDouble,
    NotEq,
    Lt,
    LtEq,
    Gt,
    GtEq,
    AndOp,
    OrOp,
    NotOp,
    Concat,
    Arrow,
    // ... Add other symbols as needed

    EOF,
}

pub struct Lexer<'a> {
    input: Peekable<Chars<'a>>,
    current_char: Option<char>,
}

impl<'a> Lexer<'a> {
    pub fn new(input: &'a str) -> Self {
        let mut lexer = Lexer {
            input: input.chars().peekable(),
            current_char: None,
        };
        lexer.advance();
        lexer
    }

    fn advance(&mut self) {
        self.current_char = self.input.next();
    }

    fn peek(&mut self) -> Option<&char> {
        self.input.peek()
    }

    fn skip_whitespace(&mut self) {
        while matches!(self.current_char, Some(c) if c.is_whitespace()) {
            self.advance();
        }
    }

    fn lex_identifier_or_keyword(&mut self) -> Token {
        let mut ident = String::new();
        while matches!(self.current_char, Some(c) if c.is_alphanumeric() || c == '_' || c == '$') {
            ident.push(self.current_char.unwrap());
            self.advance();
        }
        match ident.to_uppercase().as_str() {
            "ALL" => Token::All,
            "AND" => Token::And,
            "ANTI" => Token::Anti,
            "ANY" => Token::Any,
            "ARRAY" => Token::Array,
            "AS" => Token::As,
            "ASC" => Token::Asc,
            "ASCENDING" => Token::Ascending,
            "ASOF" => Token::Asof,
            "BETWEEN" => Token::Between,
            "BOTH" => Token::Both,
            "BY" => Token::By,
            "CASE" => Token::Case,
            "CAST" => Token::Cast,
            "CATCH" => Token::Catch,
            "COHORT" => Token::Cohort,
            "COLLATE" => Token::Collate,
            "CROSS" => Token::Cross,
            "CUBE" => Token::Cube,
            "CURRENT" => Token::Current,
            "DATE" => Token::Date,
            "DAY" => Token::Day,
            "DESC" => Token::Desc,
            "DESCENDING" => Token::Descending,
            "DISTINCT" => Token::Distinct,
            "ELSE" => Token::Else,
            "END" => Token::End,
            "EXTRACT" => Token::Extract,
            "FINAL" => Token::Final,
            "FINALLY" => Token::Finally,
            "FIRST" => Token::First,
            "FN" => Token::Fn,
            "FOLLOWING" => Token::Following,
            "FOR" => Token::For,
            "FROM" => Token::From,
            "FULL" => Token::Full,
            "FUN" => Token::Fun,
            "GROUP" => Token::Group,
            "HAVING" => Token::Having,
            "HOUR" => Token::Hour,
//             "ID" => Token::Id,
            "IF" => Token::If,
            "ILIKE" => Token::Ilike,
            "IN" => Token::In,
            "INF" => Token::Inf,
            "INNER" => Token::Inner,
            "INTERVAL" => Token::Interval,
            "IS" => Token::Is,
            "JOIN" => Token::Join,
            "KEY" => Token::Key,
            "LAST" => Token::Last,
            "LEADING" => Token::Leading,
            "LEFT" => Token::Left,
            "LET" => Token::Let,
            "LIKE" => Token::Like,
            "LIMIT" => Token::Limit,
            "MINUTE" => Token::Minute,
            "MONTH" => Token::Month,
            "NAN" | "NAN_SQL" => Token::NanSql,
            "NOT" => Token::Not,
            "NULL" | "NULL_SQL" => Token::NullSql,
            "NULLS" => Token::Nulls,
            "OFFSET" => Token::Offset,
            "ON" => Token::On,
            "OR" => Token::Or,
            "ORDER" => Token::Order,
            "OUTER" => Token::Outer,
            "OVER" => Token::Over,
            "PARTITION" => Token::Partition,
            "PRECEDING" => Token::Preceding,
            "PREWHERE" => Token::Prewhere,
            "QUARTER" => Token::Quarter,
            "RANGE" => Token::Range,
            "RETURN" => Token::Return,
            "RIGHT" => Token::Right,
            "ROLLUP" => Token::Rollup,
            "ROW" => Token::Row,
            "ROWS" => Token::Rows,
            "SAMPLE" => Token::Sample,
            "SECOND" => Token::Second,
            "SELECT" => Token::Select,
            "SEMI" => Token::Semi,
            "SETTINGS" => Token::Settings,
            "SUBSTRING" => Token::Substring,
            "THEN" => Token::Then,
            "THROW" => Token::Throw,
            "TIES" => Token::Ties,
            "TIMESTAMP" => Token::Timestamp,
            "TO" => Token::To,
            "TOP" => Token::Top,
            "TOTALS" => Token::Totals,
            "TRAILING" => Token::Trailing,
            "TRIM" => Token::Trim,
            "TRUNCATE" => Token::Truncate,
            "TRY" => Token::Try,
            "UNBOUNDED" => Token::Unbounded,
            "UNION" => Token::Union,
            "USING" => Token::Using,
            "WEEK" => Token::Week,
            "WHEN" => Token::When,
            "WHERE" => Token::Where,
            "WHILE" => Token::While,
            "WINDOW" => Token::Window,
            "WITH" => Token::With,
            "YEAR" => Token::Year,
            // Add more keywords as needed
            _ => Token::Identifier(ident),
        }
    }

    fn lex_number(&mut self) -> Token {
        let mut number = String::new();
        while matches!(self.current_char, Some(c) if c.is_numeric() || c == '.') {
            number.push(self.current_char.unwrap());
            self.advance();
        }
        Token::NumberLiteral(number)
    }

    fn lex_string(&mut self) -> Token {
        let quote_char = self.current_char.unwrap();
        self.advance(); // Skip opening quote
        let mut string = String::new();
        while let Some(c) = self.current_char {
            if c == quote_char {
                self.advance(); // Skip closing quote
                break;
            }
            if c == '\\' {
                self.advance();
                if let Some(escaped_char) = self.current_char {
                    match escaped_char {
                        'n' => string.push('\n'),
                        't' => string.push('\t'),
                        '\\' => string.push('\\'),
                        '\'' => string.push('\''),
                        '"' => string.push('"'),
                        _ => string.push(escaped_char),
                    }
                    self.advance();
                }
            } else {
                string.push(c);
                self.advance();
            }
        }
        Token::StringLiteral(string)
    }

    pub fn get_next_token(&mut self) -> Token {
        self.skip_whitespace();
        if let Some(c) = self.current_char {
            match c {
                ',' => {
                    self.advance();
                    Token::Comma
                }
                ';' => {
                    self.advance();
                    Token::Semicolon
                }
                '*' => {
                    self.advance();
                    Token::Asterisk
                }
                '(' => {
                    self.advance();
                    Token::LParen
                }
                ')' => {
                    self.advance();
                    Token::RParen
                }
                '[' => {
                    self.advance();
                    Token::LBracket
                }
                ']' => {
                    self.advance();
                    Token::RBracket
                }
                '{' => {
                    self.advance();
                    Token::LBrace
                }
                '}' => {
                    self.advance();
                    Token::RBrace
                }
                '.' => {
                    self.advance();
                    Token::Dot
                }
                '+' => {
                    self.advance();
                    Token::Plus
                }
                '-' => {
                    self.advance();
                    if self.current_char == Some('>') {
                        self.advance();
                        Token::Arrow
                    } else {
                        Token::Dash
                    }
                }
                '/' => {
                    self.advance();
                    Token::Slash
                }
                '%' => {
                    self.advance();
                    Token::Percent
                }
                ':' => {
                    self.advance();
                    Token::Colon
                }
                '?' => {
                    self.advance();
                    Token::Query
                }
                '=' => {
                    self.advance();
                    if self.current_char == Some('=') {
                        self.advance();
                        Token::EqDouble
                    } else {
                        Token::EqSingle
                    }
                }
                '!' => {
                    self.advance();
                    if self.current_char == Some('=') {
                        self.advance();
                        Token::NotEq
                    } else {
                        Token::NotOp
                    }
                }
                '<' => {
                    self.advance();
                    if self.current_char == Some('=') {
                        self.advance();
                        Token::LtEq
                    } else if self.current_char == Some('>') {
                        self.advance();
                        Token::NotEq
                    } else {
                        Token::Lt
                    }
                }
                '>' => {
                    self.advance();
                    if self.current_char == Some('=') {
                        self.advance();
                        Token::GtEq
                    } else {
                        Token::Gt
                    }
                }
                '&' => {
                    self.advance();
                    Token::AndOp
                }
                '|' => {
                    self.advance();
                    if self.current_char == Some('|') {
                        self.advance();
                        Token::Concat
                    } else {
                        Token::OrOp
                    }
                }
                '\'' | '"' => self.lex_string(),
                c if c.is_alphabetic() || c == '_' || c == '$' => self.lex_identifier_or_keyword(),
                c if c.is_numeric() => self.lex_number(),
                _ => {
                    panic!("Unknown character: {}", c);
                }
            }
        } else {
            Token::EOF
        }
    }
}
