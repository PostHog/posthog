// src/parser.rs
use crate::lexer::{Lexer, Token};
use serde::Serialize;

#[derive(Debug, Serialize)]
pub enum ASTNode {
    Select {
        columns: Vec<ASTNode>,
        from: Box<ASTNode>,
        where_clause: Option<Box<ASTNode>>,
    },
    Identifier(String),
    Literal(String),
    BinaryOp {
        left: Box<ASTNode>,
        op: String,
        right: Box<ASTNode>,
    },
}

pub struct Parser<'a> {
    lexer: Lexer<'a>,
    current_token: Token,
}

impl<'a> Parser<'a> {
    pub fn new(mut lexer: Lexer<'a>) -> Self {
        let current_token = lexer.get_next_token();
        Parser { lexer, current_token }
    }

    fn eat(&mut self, expected: Token) {
        if self.current_token == expected {
            self.current_token = self.lexer.get_next_token();
        } else {
            panic!(
                "Unexpected token {:?}, expected {:?}",
                self.current_token, expected
            );
        }
    }

    fn factor(&mut self) -> ASTNode {
        match &self.current_token {
            Token::Identifier(name) => {
                let node = ASTNode::Identifier(name.clone());
                self.current_token = self.lexer.get_next_token();
                node
            }
            Token::Literal(value) => {
                let node = ASTNode::Literal(value.clone());
                self.current_token = self.lexer.get_next_token();
                node
            }
            Token::LeftParen => {
                self.eat(Token::LeftParen);
                let node = self.expr();
                self.eat(Token::RightParen);
                node
            }
            _ => panic!("Unexpected token in factor: {:?}", self.current_token),
        }
    }

    fn expr(&mut self) -> ASTNode {
        let mut node = self.term();

        while matches!(&self.current_token, Token::Operator(op) if op == "+" || op == "-") {
            if let Token::Operator(op) = &self.current_token {
                let op_clone = op.clone();
                self.current_token = self.lexer.get_next_token();
                node = ASTNode::BinaryOp {
                    left: Box::new(node),
                    op: op_clone,
                    right: Box::new(self.term()),
                };
            }
        }

        node
    }

    fn parse_select(&mut self) -> ASTNode {
        self.eat(Token::Select);

        let mut columns = Vec::new();

        if self.current_token == Token::Asterisk {
            columns.push(ASTNode::Identifier("*".to_string()));
            self.eat(Token::Asterisk);
        } else {
            columns.push(self.expr());
            while self.current_token == Token::Comma {
                self.eat(Token::Comma);
                columns.push(self.expr());
            }
        }

        self.eat(Token::From);
        let from = Box::new(self.parse_from());

        let where_clause = if self.current_token == Token::Where {
            self.eat(Token::Where);
            Some(Box::new(self.parse_condition()))
        } else {
            None
        };

        ASTNode::Select {
            columns,
            from,
            where_clause,
        }
    }


    fn parse_from(&mut self) -> ASTNode {
        match &self.current_token {
            Token::Identifier(_) => self.factor(),
            _ => panic!("Expected table name after FROM"),
        }
    }

    fn parse_condition(&mut self) -> ASTNode {
        self.logical_expr()
    }

    fn logical_expr(&mut self) -> ASTNode {
        let mut node = self.comparison_expr();

        while matches!(&self.current_token, Token::And | Token::Or) {
            let op = match &self.current_token {
                Token::And => "AND".to_string(),
                Token::Or => "OR".to_string(),
                _ => unreachable!(),
            };
            self.current_token = self.lexer.get_next_token();
            let right = self.comparison_expr();
            node = ASTNode::BinaryOp {
                left: Box::new(node),
                op,
                right: Box::new(right),
            };
        }

        node
    }

    fn comparison_expr(&mut self) -> ASTNode {
        let mut node = self.arith_expr();

        while matches!(&self.current_token, Token::Operator(op) if op == "=" || op == ">" || op == "<" || op == ">=" || op == "<=" || op == "!=" || op == "<>") {
            if let Token::Operator(op) = &self.current_token {
                let op_clone = op.clone();
                self.current_token = self.lexer.get_next_token();
                let right = self.arith_expr();
                node = ASTNode::BinaryOp {
                    left: Box::new(node),
                    op: op_clone,
                    right: Box::new(right),
                };
            }
        }

        node
    }

    fn arith_expr(&mut self) -> ASTNode {
        let mut node = self.term();

        while matches!(&self.current_token, Token::Operator(op) if op == "+" || op == "-") {
            if let Token::Operator(op) = &self.current_token {
                let op_clone = op.clone();
                self.current_token = self.lexer.get_next_token();
                node = ASTNode::BinaryOp {
                    left: Box::new(node),
                    op: op_clone,
                    right: Box::new(self.term()),
                };
            }
        }

        node
    }

    fn term(&mut self) -> ASTNode {
        let mut node = self.factor();

        while matches!(&self.current_token, Token::Operator(op) if op == "*" || op == "/") {
            if let Token::Operator(op) = &self.current_token {
                let op_clone = op.clone();
                self.current_token = self.lexer.get_next_token();
                node = ASTNode::BinaryOp {
                    left: Box::new(node),
                    op: op_clone,
                    right: Box::new(self.factor()),
                };
            }
        }

        node
    }

    pub fn parse(&mut self) -> ASTNode {
        match self.current_token {
            Token::Select => self.parse_select(),
            _ => panic!("Unexpected token at start: {:?}", self.current_token),
        }
    }
}
