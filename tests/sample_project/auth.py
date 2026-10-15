"""用户认证与权限管理模块"""

import hashlib
import time
from typing import Optional, Dict, Any


class PasswordHasher:
    """密码哈希与加密校验器"""

    def __init__(self, salt: str = "custom_salt_secret"):
        self.salt = salt

    def hash_password(self, raw_password: str) -> str:
        """对明文密码加盐并生成 SHA256 哈希字符串"""
        salted = f"{raw_password}:{self.salt}"
        return hashlib.sha256(salted.encode("utf-8")).hexdigest()

    def verify_password(self, raw_password: str, hashed_password: str) -> bool:
        """比对用户输入的明文密码与数据库中保存的哈希值"""
        return self.hash_password(raw_password) == hashed_password


class AuthService:
    """系统登录认证与令牌发放服务"""

    def __init__(self):
        self.hasher = PasswordHasher()
        self.active_sessions: Dict[str, Dict[str, Any]] = {}

    def login(self, username: str, password_raw: str) -> Dict[str, Any]:
        """处理用户登录逻辑：校验账号密码，验证成功后签发 Session Token"""
        if not username or not password_raw:
            raise ValueError("用户名和密码不能为空")

        # 模拟从数据库获取用户信息
        stored_hash = self.hasher.hash_password("admin123")
        if username == "admin" and self.hasher.verify_password(password_raw, stored_hash):
            token = f"token_{username}_{int(time.time())}"
            self.active_sessions[token] = {"username": username, "login_time": time.time()}
            return {"status": "success", "token": token}
        else:
            return {"status": "failed", "message": "用户名或密码错误"}

    def logout(self, token: str) -> bool:
        """用户注销登录并销毁会话令牌"""
        if token in self.active_sessions:
            del self.active_sessions[token]
            return True
        return False
