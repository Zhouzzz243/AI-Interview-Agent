#!/usr/bin/env python3
"""
直接测试 LLM 调用
"""

import asyncio
import sys

# 设置控制台输出编码
sys.stdout.reconfigure(encoding='utf-8')

from app.tools.llm_client import LLMClient
from app.infrastructure.config import get_settings

async def test_llm():
    print("=" * 60)
    print("LLM Connection Test")
    print("=" * 60)
    
    # 1. 检查配置
    settings = get_settings()
    print(f"\n[1] Configuration:")
    print(f"  API Key length: {len(settings.llm.api_key)}")
    print(f"  Model: {settings.llm.model}")
    print(f"  Base URL: {settings.llm.base_url}")
    
    if len(settings.llm.api_key) == 0:
        print("\n[ERROR] API Key is empty!")
        return False
    
    # 2. 创建客户端
    client = LLMClient()
    print(f"\n[2] LLM Client:")
    print(f"  API Key length: {len(client._api_key)}")
    print(f"  Model: {client._model}")
    
    # 3. 测试调用
    print(f"\n[3] Testing LLM call...")
    try:
        result = await client.chat('Hello, test connection')
        
        print(f"\n[SUCCESS] LLM call successful!")
        print(f"  Response length: {len(result.content)}")
        print(f"  Response preview: {result.content[:100]}...")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] LLM call failed:")
        print(f"  Error type: {type(e).__name__}")
        print(f"  Error message: {str(e)}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_llm())
    
    print("\n" + "=" * 60)
    if success:
        print("RESULT: PASSED")
    else:
        print("RESULT: FAILED")
    print("=" * 60)