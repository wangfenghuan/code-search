"""文本与代码标识符自然语言增强工具库 (Code Identifier & Text Enhancement Utilities)

主要解决 bge-small-zh 等轻量自然语言模型在代码符号检索上的痛点：
1. 标识符拆词注入（Camel / Pascal / Snake / Kebab Case Splitting）：
   自动将 verifyJwtTokenSignature 或 verify_jwt_token 拆解为自然语言词组 verify jwt token signature，
   注入向量化文本，避免 Tokenizer 将长英文标识符拆成无意义碎片 sub-words。
2. 查询词自然语言展开（Query Expansion with Identifier Splits）：
   若用户查询中含有代码标识符，自动展开其拆词形式，使查询向量与代码向量在词法及语义层面紧密对齐。
"""

import re
from typing import List, Set

# 常见编程语言关键字与无语义停用词（过滤掉不影响自然语言语义的杂词）
CODE_STOPWORDS: Set[str] = {
    "def", "class", "function", "fn", "func", "return", "var", "let", "const",
    "if", "else", "for", "while", "import", "from", "export", "package", "public",
    "private", "protected", "static", "final", "void", "self", "this", "cls",
    "async", "await", "try", "catch", "except", "finally", "throw", "raise",
    "type", "interface", "struct", "new", "true", "false", "null", "none",
}


def split_camel_snake_case(name: str) -> List[str]:
    """将 camelCase, PascalCase, snake_case, kebab-case, 包含点或斜杠的标识符拆解为小写自然语言词组。

    示例:
      verify_jwt_token_signature -> ['verify', 'jwt', 'token', 'signature']
      verifyJwtTokenSignature    -> ['verify', 'jwt', 'token', 'signature']
      getHTTPResponseCode        -> ['get', 'http', 'response', 'code']
      AuthService.login          -> ['auth', 'service', 'login']
      HTTP GET /api/v1/users     -> ['http', 'get', 'api', 'v1', 'users']
    """
    if not name or not name.strip():
        return []

    # 1. 替换下划线、短横线、点、冒号、斜杠、括号等为统一分隔符
    s = re.sub(r"[_\.\-/:\\()#@,;]+", " ", name)
    # 2. 处理连续大写缩写紧跟首字母大写的单词: HTTPResponse -> HTTP Response
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    # 3. 处理小写字母或数字紧跟大写字母: verifyJwt -> verify Jwt, get2FA -> get 2FA
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    # 4. 提取有效单词
    words = []
    for token in s.split():
        token = token.strip()
        if token:
            words.append(token.lower())
    return words


def extract_natural_words_from_identifiers(*texts: str, max_words: int = 50) -> List[str]:
    """从多个代码文本/标识符片段中提取并拆解自然语言词组，去重且保留首次出现的顺序。"""
    seen: Set[str] = set()
    result: List[str] = []

    for text in texts:
        if not text:
            continue
        # 匹配代码中的标识符形态（如 methodName, class_name, API_PATH）
        raw_tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_\-\.]{2,}", text)
        if not raw_tokens:
            raw_tokens = [text]

        for token in raw_tokens:
            split_words = split_camel_snake_case(token)
            for w in split_words:
                if len(w) >= 2 and w not in CODE_STOPWORDS and w not in seen:
                    seen.add(w)
                    result.append(w)
                    if len(result) >= max_words:
                        return result
    return result


def expand_query_with_splits(query: str) -> str:
    """如果查询语句中包含 camelCase 或 snake_case 英文标识符，自动在其后展开自然语言拆词。

    示例:
      'JWT verify_token 校验' -> 'JWT verify_token (verify token) 校验'
      'verifyJwtTokenSignature' -> 'verifyJwtTokenSignature (verify jwt token signature)'
    """
    if not query or not query.strip():
        return ""

    tokens = query.split()
    expansions = []
    for tok in tokens:
        # 检查是否包含驼峰或下划线
        if ("_" in tok and len(tok) > 3) or re.search(r"[a-z][A-Z]", tok):
            splits = split_camel_snake_case(tok)
            if splits and len(splits) > 1:
                split_phrase = " ".join(splits)
                if split_phrase not in query.lower():
                    expansions.append(split_phrase)

    if expansions:
        return f"{query} ({' '.join(expansions)})"
    return query
