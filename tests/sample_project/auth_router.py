"""用户认证 HTTP API 路由控制器"""

from typing import Dict, Any
from auth import AuthService

class DummyRouter:
    def post(self, path: str):
        def decorator(fn):
            return fn
        return decorator

    def get(self, path: str):
        def decorator(fn):
            return fn
        return decorator

router = DummyRouter()
auth_service = AuthService()


@router.post("/api/v1/auth/login")
def login_api(payload: Dict[str, Any]) -> Dict[str, Any]:
    """用户登录接口：接收前端传来的用户名和密码，返回认证 Token"""
    username = payload.get("username", "")
    password = payload.get("password", "")
    return auth_service.login(username, password)


@router.get("/api/v1/auth/me")
def get_current_user_profile(token: str) -> Dict[str, Any]:
    """获取当前登录用户信息：根据 Header 中的 Token 提取用户画像与角色权限"""
    if token in auth_service.active_sessions:
        return {"status": "success", "user": auth_service.active_sessions[token]}
    return {"status": "unauthorized", "message": "无效或已过期的登录令牌"}
