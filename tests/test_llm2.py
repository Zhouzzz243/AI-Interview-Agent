#!/usr/bin/env python3
"""
强制加载环境变量并测试 LLM
"""

import asyncio
import sys
import os
from pathlib import Path

# 设置控制台输出编码
sys.stdout.reconfigure(encoding='utf-8')

# Step 1: 强制加载 .env 文件到 os.environ
from dotenv import load_dotenv
env_path = Path.cwd() / ".env"
load_dotenv(env_path, override=True)

# Step 2: 验证环境变量已加载
api_key_env = os.getenv("ZHIPUAI_API_KEY")
print(f"[Step 1] Environment variable loaded:")
print(f"  ZHIPUAI_API_KEY length: {len(api_key_env) if api_key_env else 0}")

# Step 3: 导入并测试
from app.tools.llm_client import LLMClient

async def test_llm():
    print(f"\n[Step 2] Creating LLM client...")
    
    # 直接使用环境变量中的 API Key 创建客户端（绕过 get_settings）
    client = LLMClient(api_key=api_key_env)
    
    print(f"  Client API Key length: {len(client._api_key)}")
    print(f"  Model: {client._model}")
    
    if len(client._api_key) == 0:
        print("\n[ERROR] Still empty!")
        return False
    
    # 测试调用
    print(f"\n[Step 3] Testing LLM call...")
    try:
        result = await client.chat('Hello')
        
        print(f"\n[SUCCESS] LLM call successful!")
        print(f"  Response: {result.content[:100]}...")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_llm())
    print("\n" + "=" * 60)
    print("PASSED" if success else "FAILED")
    print("=" * 60)