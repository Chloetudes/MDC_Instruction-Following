# -*- coding: utf-8 -*-
"""
clients/openai_client.py - 统一客户端（修复版 - 分离 reasoning 和 content）
"""

import json
import requests
from typing import List, Dict, Optional, Tuple, Any, Union


class OAIClient:
    """统一的OpenAI兼容客户端"""

    def __init__(self, base_url: str, api_key: str,
                 protocol: str = "openai",
                 auth_header: str = "Authorization",
                 auth_prefix: str = "Bearer",
                 extra_headers: Optional[Dict[str, str]] = None,
                 timeout: int = 120):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.protocol = protocol
        self.auth_header = auth_header
        self.auth_prefix = auth_prefix
        self.extra_headers = extra_headers or {}
        self.timeout = timeout

    def _build_headers(self) -> Dict[str, str]:
        if self.auth_prefix:
            auth_value = f"{self.auth_prefix} {self.api_key}"
        else:
            auth_value = self.api_key

        headers = {
            "Content-Type": "application/json",
            self.auth_header: auth_value
        }
        headers.update(self.extra_headers)
        return headers

    def _build_openai_payload(self, model: str, messages: List[Dict],
                              temperature: float, stream: bool = False,
                              **kwargs) -> Dict[str, Any]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream
        }
        payload.update(kwargs)
        return payload

    def _build_vertex_payload(self, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        contents = []
        for msg in messages:
            if msg["role"] == "system":
                contents.append({
                    "role": "user",
                    "parts": [{"text": f"[System]: {msg['content']}"}]
                })
            else:
                content = msg["content"]
                if isinstance(content, list):
                    parts = []
                    for item in content:
                        if item.get("type") == "text":
                            parts.append({"text": item["text"]})
                    contents.append({
                        "role": msg["role"],
                        "parts": parts
                    })
                else:
                    contents.append({
                        "role": msg["role"],
                        "parts": [{"text": content}]
                    })

        payload = {"contents": contents}
        payload.update(kwargs)
        return payload

    def _build_openai_responses_payload(self, model: str, messages: List[Dict],
                                        temperature: float, stream: bool = False,
                                        **kwargs) -> Dict[str, Any]:
        payload = {
            "model": model,
            "input": messages,
            "temperature": temperature,
            "stream": stream
        }
        payload.update(kwargs)
        return payload

    def _build_dashscope_payload(self, model: str, messages: List[Dict],
                                 temperature: float, stream: bool = False,
                                 **kwargs) -> Dict[str, Any]:
        formatted_messages = []
        for msg in messages:
            content = msg["content"]
            formatted_msg = {
                "role": msg["role"],
                "content": content if isinstance(content, str) else str(content)
            }
            formatted_messages.append(formatted_msg)

        payload = {
            "model": model,
            "input": {
                "messages": formatted_messages
            },
            "parameters": {
                "result_format": "message",
                "temperature": temperature,
            }
        }

        if kwargs.get("enable_thinking", True):
            payload["parameters"]["enable_thinking"] = True

        if kwargs.get("enable_search", False):
            payload["parameters"]["enable_search"] = True
            payload["parameters"]["search_options"] = {
                "search_strategy": kwargs.get("search_strategy", "agent_max"),
                "enable_source": kwargs.get("enable_source", True)
            }

        if kwargs.get("enable_code_interpreter", False):
            payload["parameters"]["enable_code_interpreter"] = True

        return payload

    def _build_url(self, model: str = None) -> str:
        if self.protocol == "vertex":
            if not model:
                raise ValueError("Vertex协议需要指定model")
            return f"{self.base_url}/models/{model}:generateContent"
        elif self.protocol == "openai_responses":
            return f"{self.base_url}"
        elif self.protocol == "dashscope":
            return self.base_url
        else:
            return f"{self.base_url}/chat/completions"

    def _parse_openai_response(self, result: Dict) -> str:
        if "choices" in result and len(result["choices"]) > 0:
            return result["choices"][0]["message"]["content"]
        return str(result)

    def _parse_vertex_response(self, result: Dict) -> str:
        if "candidates" in result and len(result["candidates"]) > 0:
            candidate = result["candidates"][0]
            if "content" in candidate and "parts" in candidate["content"]:
                parts = candidate["content"]["parts"]
                return "".join(part.get("text", "") for part in parts)
        return str(result)

    def _parse_openai_responses_response(self, result: Dict) -> str:
        if "output" in result:
            return result["output"]
        return str(result)

    def _parse_dashscope_response(self, result: Dict,
                                  return_reasoning: bool = False) -> Union[str, Tuple[str, str]]:
        try:
            output = result.get("output", {})
            choices = output.get("choices", [])

            if not choices:
                if "text" in output:
                    return (output["text"], "") if return_reasoning else output["text"]
                return (str(result), "") if return_reasoning else str(result)

            message = choices[0].get("message", {})
            content = message.get("content", "")
            reasoning = message.get("reasoning_content", "")

            if return_reasoning:
                return content, reasoning
            else:
                return content

        except Exception as e:
            error_msg = f"<error: 解析失败 - {str(e)}>"
            return (error_msg, "") if return_reasoning else error_msg

    def chat(self, model: str, messages: List[Dict],
             temperature: float = 0.7, **kwargs) -> str:
        url = self._build_url(model)
        headers = self._build_headers()

        if self.protocol == "dashscope":
            payload = self._build_dashscope_payload(
                model, messages, temperature, stream=False, **kwargs
            )
        elif self.protocol == "vertex":
            payload = self._build_vertex_payload(messages, **kwargs)
        elif self.protocol == "openai_responses":
            payload = self._build_openai_responses_payload(
                model, messages, temperature, **kwargs
            )
        else:
            payload = self._build_openai_payload(
                model, messages, temperature, **kwargs
            )

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()

            if self.protocol == "dashscope":
                return self._parse_dashscope_response(result, return_reasoning=False)
            elif self.protocol == "vertex":
                return self._parse_vertex_response(result)
            elif self.protocol == "openai_responses":
                return self._parse_openai_responses_response(result)
            else:
                return self._parse_openai_response(result)

        except requests.exceptions.Timeout:
            raise TimeoutError(f"请求超时 ({self.timeout}s)")
        except requests.exceptions.HTTPError as e:
            try:
                error_detail = e.response.json()
                error_msg = error_detail.get("message", str(e))
            except Exception:
                error_msg = f"{str(e)}\n{e.response.text[:200]}"
            raise RuntimeError(f"请求失败: {error_msg}")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"请求失败: {str(e)}")

    def chat_with_meta(self, model: str, messages: List[Dict],
                       temperature: float = 0.7, **kwargs) -> Tuple[str, Optional[str], Optional[str]]:
        """发送聊天请求并返回元数据

        Returns:
            (content, finish_reason, reasoning)
        """
        url = self._build_url(model)
        headers = self._build_headers()

        if self.protocol == "vertex":
            payload = self._build_vertex_payload(messages, **kwargs)
        elif self.protocol == "openai_responses":
            payload = self._build_openai_responses_payload(
                model, messages, temperature, **kwargs
            )
        elif self.protocol == "dashscope":
            payload = self._build_dashscope_payload(
                model, messages, temperature, **kwargs
            )
        else:
            payload = self._build_openai_payload(
                model, messages, temperature, **kwargs
            )

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()

            text = None
            finish_reason = None
            reasoning = None

            if self.protocol == "vertex":
                text = self._parse_vertex_response(result)
                if "candidates" in result and len(result["candidates"]) > 0:
                    finish_reason = result["candidates"][0].get("finishReason")
            elif self.protocol == "openai_responses":
                text = self._parse_openai_responses_response(result)
                finish_reason = result.get("finish_reason")
            elif self.protocol == "dashscope":
                text, reasoning = self._parse_dashscope_response(result, return_reasoning=True)
                output = result.get("output", {})
                choices = output.get("choices", [])
                if choices:
                    finish_reason = choices[0].get("finish_reason")
                    if finish_reason == 'null':
                        finish_reason = None
            else:
                if "choices" in result and len(result["choices"]) > 0:
                    choice = result["choices"][0]
                    text = choice["message"]["content"]
                    finish_reason = choice.get("finish_reason")

            return text or str(result), finish_reason, reasoning

        except requests.exceptions.Timeout:
            raise TimeoutError(f"请求超时 ({self.timeout}s)")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"请求失败: {str(e)}")
