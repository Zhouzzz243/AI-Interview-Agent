#!/usr/bin/env python3
"""
测试直接通过 os.getenv 获取环境变量
"""

import os
from dotenv import load_dotenv

# 直接加载 .env 文件
load_dotenv(".env", override=True)

# 测试获取 ZHIPUAI_API_KEY
api_key = os.getenv("ZHIPUAI_API_KEY")
print(f"ZHIPUAI_API_KEY length: {len(api_key) if api_key else 0}")
print(f"ZHIPUAI_API_KEY: {api_key}")

# 测试其他环境变量
model = os.getenv("ZHIPUAI_MODEL")
print(f"ZHIPUAI_MODEL: {model}")

# 测试从 config.py 加载
from app.infrastructure.config import get_settings
settings = get_settings()
print(f"\nFrom get_settings():")
print(f"llm.api_key length: {len(settings.llm.api_key)}")
print(f"llm.api_key: {settings.llm.api_key}")
print(f"llm.model: {settings.llm.model}")