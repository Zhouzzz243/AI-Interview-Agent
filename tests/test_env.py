#!/usr/bin/env python3
"""
测试 .env 文件路径和加载
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# 测试当前目录
print("Current directory:", os.getcwd())

# 测试 .env 文件是否存在
current_env = Path(".env")
print(f".env exists in current dir: {current_env.exists()}")
if current_env.exists():
    print(f".env size: {current_env.stat().st_size} bytes")
    # 读取前几行
    with open(current_env, 'r', encoding='utf-8') as f:
        lines = f.readlines()[:10]
        print("First 10 lines:")
        for line in lines:
            print(line.rstrip())

# 测试从 config.py 路径加载
try:
    from app.infrastructure.config import get_settings
    settings = get_settings()
    print(f"\nFrom get_settings():")
    print(f"API Key length: {len(settings.llm.api_key)}")
    print(f"API Key (first 10 chars): {settings.llm.api_key[:10]}...")
    print(f"Model: {settings.llm.model}")
    print(f"Base URL: {settings.llm.base_url}")
except Exception as e:
    print(f"Error loading settings: {e}")

# 直接测试 load_dotenv
print("\nTesting direct load_dotenv:")
env_path = Path(".env")
if env_path.exists():
    load_dotenv(env_path, encoding="utf-8", override=True)
    api_key = os.getenv("ZHIPUAI_API_KEY")
    print(f"Direct load - API Key length: {len(api_key) if api_key else 0}")
    print(f"Direct load - API Key: {api_key[:10]}..." if api_key else "No API key")
else:
    print(".env file not found")