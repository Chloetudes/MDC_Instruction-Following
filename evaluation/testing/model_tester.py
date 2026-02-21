# -*- coding: utf-8 -*-
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import pandas as pd
from tqdm import tqdm

from config import get_provider, get_provider_for_model
from clients.openai_client import OAIClient
from evaluation.core.utils import safe_save_excel


class ModelAvailabilityTester:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.test_prompt = "请用一句话介绍你自己。"

    def test_single_model(self, provider: str, model: str) -> Dict:
        try:
            pc = get_provider(provider)
            client = OAIClient(
                base_url=pc.base_url,
                api_key=pc.api_key,
                protocol=pc.protocol,
                auth_header=pc.auth_header,
                auth_prefix=pc.auth_prefix,
                extra_headers=pc.extra_headers,
                timeout=self.timeout
            )
            messages = [{"role": "user", "content": self.test_prompt}]
            start_time = time.time()
            response = client.chat(model=model, messages=messages, temperature=0.3)
            elapsed_time = time.time() - start_time

            if isinstance(response, str):
                is_error = (
                    response.startswith('<error') or
                    response.startswith('<!DOCTYPE') or
                    response.startswith('<html') or
                    'IRC-001' in response or
                    '没有当前模型的权限' in response or
                    'permission denied' in response.lower() or
                    'unauthorized' in response.lower()
                )
                if is_error:
                    return {'provider': provider, 'model': model, 'available': False,
                            'error': response[:200], 'response_time': elapsed_time}

            return {
                'provider': provider, 'model': model, 'available': True,
                'error': None, 'response_time': elapsed_time,
                'response_preview': response[:100] if isinstance(response, str) else str(response)[:100]
            }
        except Exception as e:
            return {'provider': provider, 'model': model, 'available': False,
                    'error': str(e), 'response_time': None}

    def test_all_models(self, model_configs: List[Dict[str, str]], max_workers: int = 3) -> pd.DataFrame:
        print(f"\n{'=' * 60}")
        print(f"🧪 模型可用性测试")
        print(f"{'=' * 60}\n")
        print(f"  待测试模型数: {len(model_configs)}")
        print(f"  并发数: {max_workers}")
        print(f"  超时时间: {self.timeout}秒\n")

        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for cfg in model_configs:
                try:
                    provider = cfg.get('provider') or get_provider_for_model(cfg['model']).name
                    future = executor.submit(self.test_single_model, provider, cfg['model'])
                    futures[future] = cfg
                except Exception as e:
                    results.append({'provider': 'unknown', 'model': cfg['model'],
                                    'available': False, 'error': f"配置错误: {str(e)}", 'response_time': None})

            for future in tqdm(as_completed(futures), total=len(futures), desc="🔄 测试进度", ncols=100):
                try:
                    results.append(future.result())
                except Exception as e:
                    cfg = futures[future]
                    results.append({'provider': cfg.get('provider', 'unknown'), 'model': cfg['model'],
                                    'available': False, 'error': str(e), 'response_time': None})

        df = pd.DataFrame(results)
        available_count = df['available'].sum()
        unavailable_count = len(df) - available_count

        print(f"\n{'=' * 60}")
        print(f"✅ 测试完成 — 可用: {available_count}  不可用: {unavailable_count}")
        print(f"{'=' * 60}")

        if available_count > 0:
            print(f"\n✅ 可用模型列表:")
            for _, row in df[df['available']].sort_values('response_time').iterrows():
                print(f"  ✓ {row['provider']:20s} / {row['model']:35s} ({row['response_time']:.2f}秒)")

        if unavailable_count > 0:
            print(f"\n❌ 不可用模型列表:")
            for _, row in df[~df['available']].iterrows():
                error_preview = str(row['error'])[:80] + "..." if len(str(row['error'])) > 80 else str(row['error'])
                print(f"  ✗ {row['provider']:20s} / {row['model']:35s}")
                print(f"    原因: {error_preview}")

        print(f"{'=' * 60}\n")
        return df


def select_best_judge_model(test_results: pd.DataFrame,
                             preferred_models: Optional[List[str]] = None) -> Optional[Dict[str, str]]:
    available_models = test_results[test_results['available'] == True]
    if len(available_models) == 0:
        print("❌ 没有可用的模型")
        return None

    if preferred_models is None:
        preferred_models = [
            "claude-sonnet-4-5-20250929", "claude-opus-4-5-20251101",
            "gpt-5.2-chat-latest", "gpt-4o",
            "gemini-3-pro-preview", "deepseek-v3.2-exp", "qwen3-max"
        ]

    for model_name in preferred_models:
        match = available_models[available_models['model'] == model_name]
        if len(match) > 0:
            row = match.iloc[0]
            print(f"✅ 选择裁判模型: {row['provider']} / {row['model']}")
            return {'provider': row['provider'], 'model': row['model']}

    fastest = available_models.sort_values('response_time').iloc[0]
    print(f"✅ 选择裁判模型（最快响应）: {fastest['provider']} / {fastest['model']}")
    return {'provider': fastest['provider'], 'model': fastest['model']}
