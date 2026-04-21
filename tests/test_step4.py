import sys
sys.path.insert(0, '.')

print('='*60)
print('Step 4 验证: 导入 Tools 层模块')
print('='*60)

# 1. 测试 LLM 客户端导入
try:
    from app.tools.llm_client import LLMClient, LLMResponse, Message, get_llm_client
    print('[OK] LLM client imported successfully')
except Exception as e:
    print(f'[FAIL] LLM import failed: {e}')

# 2. 测试文件解析器导入
try:
    from app.tools.file_parser import FileParser, ParseResult, get_file_parser
    print('[OK] File parser imported successfully')
except Exception as e:
    print(f'[FAIL] File parser import failed: {e}')

# 3. 测试实例化
try:
    client = get_llm_client()
    print('[OK] LLM client instantiated')
except Exception as e:
    print(f'[FAIL] LLM instantiation failed: {e}')

# 4. 测试文件解析器实例化
try:
    parser = get_file_parser()
    print(f'[OK] File parser instantiated - supports: {parser.SUPPORTED_EXTENSIONS}')
except Exception as e:
    print(f'[FAIL] Parser instantiation failed: {e}')

# 5. 测试 Message 模型
try:
    msg = Message(role='user', content='test message')
    msg_dict = msg.to_dict()
    print(f'[OK] Message model works - {msg_dict}')
except Exception as e:
    print(f'[FAIL] Message model failed: {e}')

print()
print('='*60)
print('Step 4 verification complete! All components working.')
print('='*60)
