import sys
sys.path.insert(0, '.')

print('='*60)
print('Step 5 Verification: External Services Layer')
print('='*60)

# 1. Test OSS Client
try:
    from app.infrastructure.oss_client import OSSClient, UploadResult, DownloadResult, get_oss_client
    oss = get_oss_client()
    print(f'[OK] OSS Client imported and instantiated')
    print(f'    - Available: {oss.is_available()} (expected: False without real credentials)')
except Exception as e:
    print(f'[FAIL] OSS Client: {e}')

# 2. Test Redis Client
try:
    from app.infrastructure.redis_client import RedisClient, get_redis_client
    redis = get_redis_client()
    print(f'[OK] Redis Client imported and instantiated')
    print(f'    - Available: {redis.is_available()} (expected: False if Redis not running)')
    print(f'    - Methods: set_json, get_json, save_session_state, etc.')
except Exception as e:
    print(f'[FAIL] Redis Client: {e}')

# 3. Test ChromaDB Vector Store
try:
    from app.infrastructure.vector_store import VectorStore, Document, SearchResult, get_vector_store
    store = get_vector_store()
    print(f'[OK] ChromaDB VectorStore imported and instantiated')
    print(f'    - Available: {store.is_available()}')
    print(f'    - Collections: {store.list_collections()}')
except Exception as e:
    print(f'[FAIL] VectorStore: {e}')
    import traceback
    traceback.print_exc()

# 4. Test Document model
try:
    from app.infrastructure.vector_store import Document
    doc = Document(
        content="HashMap底层是数组+链表+红黑树",
        metadata={"category": "jvm", "difficulty": "medium"}
    )
    print(f'[OK] Document model works - content preview: {doc.content[:30]}...')
except Exception as e:
    print(f'[FAIL] Document model: {e}')

# 5. Test SearchResult model
try:
    from app.infrastructure.vector_store import SearchResult
    result = SearchResult(
        id="doc_001",
        content="JVM内存结构包括堆、栈、方法区...",
        metadata={"source": "eight_part_qa"},
        distance=0.92
    )
    print(f'[OK] SearchResult model works - score: {result.distance:.2f}')
except Exception as e:
    print(f'[FAIL] SearchResult model: {e}')

# 6. Test infrastructure __init__ exports
try:
    from app.infrastructure import (
        get_oss_client,
        get_redis_client,
        get_vector_store,
        OSSClient,
        RedisClient,
        VectorStore,
        OssError,
        VectorDbError
    )
    print(f'[OK] All external service clients exported from infrastructure package')
except Exception as e:
    print(f'[FAIL] Package exports: {e}')

print()
print('='*60)
print('Step 5 verification complete!')
print('='*60)
