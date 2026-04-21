#!/usr/bin/env python3
"""
深度调试：检查 pydantic Settings 如何读取环境变量
"""

import os
from pathlib import Path
from dotenv import load_dotenv

print("=" * 70)
print("Deep Debug: Pydantic Settings Environment Loading")
print("=" * 70)

# Step 1: 直接使用 dotenv 加载
env_path = Path.cwd() / ".env"
print(f"\n[Step 1] Direct dotenv loading:")
print(f"  env_path = {env_path}")
print(f"  exists = {env_path.exists()}")

load_dotenv(env_path, override=True)
api_key_direct = os.getenv("ZHIPUAI_API_KEY")
print(f"  ZHIPUAI_API_KEY (direct) length = {len(api_key_direct) if api_key_direct else 0}")

# Step 2: 使用 pydantic BaseSettings 测试
print(f"\n[Step 2] Pydantic BaseSettings test:")

from pydantic_settings import BaseSettings, SettingsConfigDict

class TestLLMSettings(BaseSettings):
    api_key: str = ""
    model: str = "glm-4-plus"

    model_config = SettingsConfigDict(
        env_file=str(env_path),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="ZHIPUAI_"
    )

test_llm = TestLLMSettings()
print(f"  api_key length = {len(test_llm.api_key)}")
print(f"  api_key (first 10) = {test_llm.api_key[:10]}...")
print(f"  model = {test_llm.model}")

# Step 3: 检查实际的 Settings 类
print(f"\n[Step 3] Actual Settings class:")

from app.infrastructure.config import Settings, LLMSettings

# 先测试 LLMSettings 单独实例化
llm_settings = LLMSettings()
print(f"  LLMSettings.api_key length = {len(llm_settings.api_key)}")
print(f"  LLMSettings.api_key (first 10) = {llm_settings.api_key[:10]}...")

# Step 4: 完整的 Settings 类
settings = Settings()
print(f"\n[Step 4] Full Settings class:")
print(f"  settings.llm.api_key length = {len(settings.llm.api_key)}")
print(f"  settings.llm.api_key (first 10) = {settings.llm.api_key[:10]}...")

# Step 5: 检查 ZHIPUAI_ 前缀的环境变量
print(f"\n[Step 5] All ZHIPUAI_* environment variables:")
for key, value in os.environ.items():
    if key.startswith("ZHIPUAI_"):
        print(f"  {key} = {value[:20]}..." if len(value) > 20 else f"  {key} = {value}")

print("\n" + "=" * 70)