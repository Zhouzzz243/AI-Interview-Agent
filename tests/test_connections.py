import sys
import asyncio
sys.path.insert(0, '.')

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path('.') / '.env', override=True)

from app.infrastructure.config import get_settings
get_settings.cache_clear()

print('='*60)
print('  Full Connection Test - All Services')
print('='*60)
print()

results = []

# 1. Test ZhipuAI LLM
print('[1/4] Testing ZhipuAI GLM-4...')
try:
    from app.tools.llm_client import get_llm_client, reset_llm_client

    reset_llm_client()
    client = get_llm_client()

    if client._api_key and client._api_key != 'your_api_key_here':
        print(f'   [OK] API Key configured: {client._api_key[:10]}...{client._api_key[-6:]}')

        async def test_llm():
            response = await client.chat("Hello, introduce yourself in one sentence", temperature=0.5)
            return response

        response = asyncio.run(test_llm())
        print(f'   [OK] LLM call successful!')
        print(f'   Response: {response.content[:100]}...')
        print(f'   Tokens: {response.total_tokens} (in:{response.prompt_tokens} out:{response.completion_tokens})')
        print(f'   Latency: {response.latency_ms:.0f}ms')
        results.append(('ZhipuAI GLM-4', True, f'{response.latency_ms:.0f}ms'))
    else:
        print('   [FAIL] API Key not configured!')
        results.append(('ZhipuAI GLM-4', False, 'API Key missing'))

except Exception as e:
    print(f'   [FAIL] Connection failed: {e}')
    results.append(('ZhipuAI GLM-4', False, str(e)))

print()

# 2. Test Aliyun OSS
print('[2/4] Testing Aliyun OSS...')
try:
    from app.infrastructure.oss_client import get_oss_client

    oss = get_oss_client()

    if oss.is_available():
        print(f'   [OK] OSS connected!')
        print(f'   Bucket: {oss._bucket_name}')
        print(f'   Endpoint: {oss._endpoint}')

        async def test_oss_upload():
            test_data = b'Test file for connection verification'
            result = await oss.upload_file(
                file_data=test_data,
                filename='connection_test.txt',
                folder='_test/'
            )
            return result

        upload_result = asyncio.run(test_oss_upload())
        print(f'   [OK] Upload test successful!')
        print(f'   URL: {upload_result.file_url[:60]}...')
        print(f'   Size: {upload_result.file_size} bytes')

        async def test_oss_delete():
            await oss.delete_file(upload_result.object_key)
            return True

        asyncio.run(test_oss_delete())
        print(f'   [OK] Cleanup successful!')

        results.append(('Aliyun OSS', True, upload_result.file_url[:30]))
    else:
        print(f'   [WARN] OSS not configured (acceptable in dev mode)')
        results.append(('Aliyun OSS', False, 'Not configured'))

except Exception as e:
    print(f'   [FAIL] Connection failed: {e}')
    results.append(('Aliyun OSS', False, str(e)))

print()

# 3. Test Redis
print('[3/4] Testing Redis...')
try:
    from app.infrastructure.redis_client import get_redis_client

    redis = get_redis_client()

    if redis.is_available():
        print(f'   [OK] Redis connected!')
        print(f'   Host: {redis._host}:{redis._port}')
        print(f'   DB: {redis._db}')

        async def test_redis():
            test_key = '_test:connection_check'
            test_value = {'timestamp': '2026-04-14', 'status': 'ok'}

            await redis.set_json(test_key, test_value, ttl=60)

            loaded = await redis.get_json(test_key)

            await redis.delete(test_key)

            return loaded

        loaded = asyncio.run(test_redis())
        print(f'   [OK] Read/Write test passed!')
        print(f'   Data: {loaded}')
        results.append(('Redis', True, f'{redis._host}:{redis._port}'))
    else:
        print(f'   [FAIL] Redis not connected!')
        results.append(('Redis', False, 'Not running'))

except Exception as e:
    print(f'   [FAIL] Connection failed: {e}')
    results.append(('Redis', False, str(e)))

print()

# 4. Test ChromaDB
print('[4/4] Testing ChromaDB Vector Store...')
try:
    from app.infrastructure.vector_store import get_vector_store, Document

    store = get_vector_store()

    if store.is_available():
        print(f'   [OK] ChromaDB connected!')
        print(f'   Persist dir: {store._persist_dir}')
        print(f'   Collections: {store.list_collections()}')

        async def test_chromadb():
            test_doc = Document(
                content="HashMap is the most commonly used Map implementation in Java",
                metadata={"category": "test", "source": "connection_test"}
            )

            count_before = await store.count()

            await store.add_documents([test_doc])

            count_after = await store.count()

            search_results = await store.query("HashMap data structure", top_k=1)

            if search_results:
                await store.delete(ids=[search_results[0].id])

            return {
                'before': count_before,
                'after': count_after,
                'search_result': search_results[0] if search_results else None
            }

        test_result = asyncio.run(test_chromadb())
        print(f'   [OK] Add document: {test_result["before"]} -> {test_result["after"]}')
        if test_result['search_result']:
            sr = test_result['search_result']
            print(f'   [OK] Semantic search:')
            print(f'      Similarity: {sr.distance:.3f}')
            print(f'      Content: {sr.content[:50]}...')

        results.append(('ChromaDB RAG', True, f'{len(store.list_collections())} collections'))
    else:
        print(f'   [FAIL] ChromaDB not initialized!')
        results.append(('ChromaDB RAG', False, 'Init failed'))

except Exception as e:
    print(f'   [FAIL] Connection failed: {e}')
    import traceback
    traceback.print_exc()
    results.append(('ChromaDB RAG', False, str(e)))

print()
print('='*60)
print('  Test Results Summary')
print('='*60)

all_passed = True
for name, success, detail in results:
    status = '[PASS]' if success else '[FAIL]'
    print(f'  {status}  {name:<15} -> {detail}')
    if not success:
        all_passed = False

print()
if all_passed:
    print('>> All services connected! Ready for Step 6 development! <<')
else:
    print('>> Some services failed. Check configuration and retry. <<')

print('='*60)
