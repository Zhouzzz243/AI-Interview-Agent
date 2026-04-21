#!/usr/bin/env python3
"""
调试 .env 文件加载问题
"""

from pathlib import Path
import os

print("=" * 60)
print("Debug: .env file loading")
print("=" * 60)

# 1. 检查 __file__ 路径
config_file = Path(r"D:\agentproject\AI-Interview-Agent-python\app\infrastructure\config.py")
print(f"\n1. Config file path:")
print(f"   config_file = {config_file}")
print(f"   exists = {config_file.exists()}")

# 2. 计算各种 parent 路径
print(f"\n2. Parent paths:")
print(f"   .parent          = {config_file.parent}")           # app/infrastructure/
print(f"   .parent.parent   = {config_file.parent.parent}")    # app/
print(f"   .parent.parent.parent = {config_file.parent.parent.parent}")  # 项目根目录

# 3. 测试不同的 .env 路径
env_path_2 = config_file.parent.parent / ".env"       # app/.env (错误)
env_path_3 = config_file.parent.parent.parent / ".env" # 项目根目录/.env (正确)

print(f"\n3. Testing .env paths:")
print(f"   Path with 2 parents: {env_path_2}")
print(f"     exists = {env_path_2.exists()}")
print(f"   Path with 3 parents: {env_path_3}")
print(f"     exists = {env_path_3.exists()}")

# 4. 直接测试当前工作目录的 .env
current_env = Path.cwd() / ".env"
print(f"\n4. Current working directory:")
print(f"   cwd = {Path.cwd()}")
print(f"   .env exists = {current_env.exists()}")

if current_env.exists():
    print(f"   .env size = {current_env.stat().st_size} bytes")
    
    # 读取 API Key 行
    with open(current_env, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('ZHIPUAI_API_KEY='):
                api_key = line.split('=', 1)[1].strip()
                print(f"   ZHIPUAI_API_KEY found!")
                print(f"   Key length = {len(api_key)}")
                print(f"   Key (first 10) = {api_key[:10]}...")
                break

# 5. 测试 Settings 类的 env_file 配置
print("\n5. Checking Settings class configuration:")

class TestSettings:
    model_config = {
        "env_file": str(config_file.parent.parent / ".env"),
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore"
    }

print(f"   Settings.env_file = {TestSettings.model_config['env_file']}")
print(f"   This path exists? = {Path(TestSettings.model_config['env_file']).exists()}")

print("\n" + "=" * 60)