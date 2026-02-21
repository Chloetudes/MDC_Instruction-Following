# -*- coding: utf-8 -*-
from threading import Lock
from typing import Dict, List, Set


class ModelBlacklist:
    def __init__(self):
        self.blacklist: Set[str] = set()
        self.lock = Lock()
        self.failure_reasons: Dict[str, str] = {}
        self.first_task_tested: Set[str] = set()

    def _key(self, provider: str, model: str) -> str:
        return f"{provider}::{model}"

    def add(self, provider: str, model: str, reason: str = ""):
        with self.lock:
            key = self._key(provider, model)
            self.blacklist.add(key)
            self.failure_reasons[key] = reason

    def is_blacklisted(self, provider: str, model: str) -> bool:
        with self.lock:
            return self._key(provider, model) in self.blacklist

    def mark_first_task_tested(self, provider: str, model: str):
        with self.lock:
            self.first_task_tested.add(self._key(provider, model))

    def is_first_task_tested(self, provider: str, model: str) -> bool:
        with self.lock:
            return self._key(provider, model) in self.first_task_tested

    def get_reason(self, provider: str, model: str) -> str:
        with self.lock:
            return self.failure_reasons.get(self._key(provider, model), "未知原因")

    def get_all(self) -> List[Dict[str, str]]:
        with self.lock:
            result = []
            for key in self.blacklist:
                provider, model = key.split("::")
                result.append({
                    'provider': provider,
                    'model': model,
                    'reason': self.failure_reasons.get(key, "")
                })
            return result

    def print_summary(self):
        blacklist = self.get_all()
        if not blacklist:
            return
        print(f"\n{'=' * 60}")
        print(f"⚠️  本次运行中被禁用的模型 ({len(blacklist)} 个)")
        print(f"{'=' * 60}")
        for item in blacklist:
            print(f"  ❌ {item['provider']} / {item['model']}")
            if item['reason']:
                reason_preview = item['reason'][:100] + "..." if len(item['reason']) > 100 else item['reason']
                print(f"     原因: {reason_preview}")
        print(f"  💡 提示: 黑名单仅在本次运行有效，下次运行会重新验证")
        print(f"{'=' * 60}\n")


MODEL_BLACKLIST = ModelBlacklist()


def is_permission_error(error_msg: str) -> bool:
    error_keywords = [
        'IRC-001', '没有当前模型的权限', '资源限制策略',
        'permission denied', 'access denied', 'unauthorized',
        'forbidden', '403', 'quota exceeded', 'rate limit', 'BadRequestError'
    ]
    error_msg_lower = error_msg.lower()
    return any(keyword.lower() in error_msg_lower for keyword in error_keywords)
