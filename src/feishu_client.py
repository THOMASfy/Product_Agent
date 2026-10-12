"""飞书开放平台 API 客户端：鉴权 + 发送群消息。"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


class FeishuAPIError(Exception):
    def __init__(self, code: int, msg: str, log_id: str | None = None):
        self.code = code
        self.msg = msg
        self.log_id = log_id
        super().__init__(f"Feishu API error {code}: {msg} (log_id={log_id})")


class FeishuClient:
    DEFAULT_BASE_URL = "https://open.feishu.cn"

    def __init__(self, app_id: str, app_secret: str, base_url: str | None = None):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._tenant_access_token: str | None = None
        self._token_expire_at: float = 0

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        use_token: bool = True,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if use_token:
            headers["Authorization"] = f"Bearer {self.get_tenant_access_token()}"

        url = f"{self.base_url}{path}"
        response = requests.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=headers,
            timeout=30,
        )

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if not response.ok:
            if isinstance(payload, dict):
                raise FeishuAPIError(
                    code=int(payload.get("code", response.status_code)),
                    msg=str(payload.get("msg", response.text)),
                    log_id=payload.get("log_id"),
                )
            response.raise_for_status()

        if not isinstance(payload, dict):
            raise FeishuAPIError(
                code=-1,
                msg=f"invalid JSON response: {response.text[:200]}",
            )

        if payload.get("code") != 0:
            raise FeishuAPIError(
                code=payload.get("code", -1),
                msg=payload.get("msg", "unknown error"),
                log_id=payload.get("log_id"),
            )
        return payload

    def get_tenant_access_token(self) -> str:
        """获取 tenant_access_token，带简单缓存。"""
        now = time.time()
        if self._tenant_access_token and now < self._token_expire_at - 60:
            return self._tenant_access_token

        payload = self._request(
            "POST",
            "/open-apis/auth/v3/tenant_access_token/internal",
            json_body={
                "app_id": self.app_id,
                "app_secret": self.app_secret,
            },
            use_token=False,
        )
        token = payload["tenant_access_token"]
        expire = payload.get("expire", 7200)

        self._tenant_access_token = token
        self._token_expire_at = now + expire
        logger.debug("Refreshed tenant_access_token, expire in %ss", expire)
        return token

    def send_message_to_chat(
        self,
        chat_id: str,
        msg_type: str,
        content: str,
    ) -> dict[str, Any]:
        """
        向群聊发送消息。

        POST /open-apis/im/v1/messages?receive_id_type=chat_id
        文档：https://open.feishu.cn/document/server-docs/im-v1/message/create
        """
        payload = self._request(
            "POST",
            "/open-apis/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            json_body={
                "receive_id": chat_id,
                "msg_type": msg_type,
                "content": content,
            },
        )
        return payload.get("data", {})
