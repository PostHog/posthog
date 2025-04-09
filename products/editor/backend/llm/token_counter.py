import tiktoken


def get_token_count(content: str):
    encoding = tiktoken.get_encoding("o200k_base")
    return len(encoding.encode(content))
