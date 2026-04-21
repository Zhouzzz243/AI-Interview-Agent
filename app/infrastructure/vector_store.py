"""
ChromaDB 向量数据库客户端 - RAG 核心组件

【Java 类比】
- 类似封装了 Milvus / Pinecone / Weaviate SDK 的 VectorStoreService
- 或者类似 Spring AI 的 VectorStore 接口实现
- 职责：存储和检索八股文标准答案、面试题库等向量数据

【RAG 工作原理】
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│ 用户问题      │ ──> │ Embedding    │ ──> │ 向量相似度检索   │
│ "HashMap原理"│     │ 模型向量化   │     │ (cosine similarity)│
└─────────────┘     └──────────────┘     └────────┬────────┘
                                                 │
                                                 ▼
                                        ┌─────────────────┐
                                        │ 返回 Top-K 相关  │
                                        │ 参考答案         │
                                        └─────────────────┘

【ChromaDB vs 其他向量库对比】
| 特性 | ChromaDB | Milvus | Pinecone |
|------|----------|--------|----------|
| 部署难度 | 🟢 嵌入式 | 🔴 集群 | ☁️ 云服务 |
| 中文支持 | ✅ BGE模型 | ✅ 自定义 | ✅ OpenAI |
| 适合规模 | <100万条 | 亿级 | 亿级 |
| 学习成本 | 低 | 中 | 低 |

【使用场景】
1. 八股文库: 存储 Java/MySQL/Redis 等标准答案
2. 项目题库: 存储常见项目问题和优秀回答
3. 场景题库: 存储系统设计类问题的参考方案

【Embedding 模型选择】
- BAAI/bge-large-zh-v1.5: 中文效果最好（我们选的）
- 支持中文语义理解，适合面试场景
"""

import os
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.infrastructure.config import get_settings
from app.infrastructure.logger import get_logger
from app.infrastructure.error_handler import VectorDbError, EmbeddingError

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """
    向量检索结果

    【字段说明】
    - id: 文档唯一ID
    - content: 文档原始文本内容
    - metadata: 元数据（来源、分类、难度等）
    - score/distance: 相似度分数（0-1，越高越相似）
    """

    id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    distance: float = 0.0

    def __str__(self) -> str:
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"SearchResult(id={self.id[:8]}..., content={preview}, score={self.distance:.3f})"


@dataclass
class Document:
    """待入库的文档"""

    content: str                    # 文档文本内容
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: Optional[str] = None         # 可选的自定义ID


class VectorStore:
    """
    ChromaDB 向量数据库核心类

    【Java 类比】
    ```java
    @Service
    public class VectorStoreServiceImpl implements VectorStoreService {
        @Autowired
        private EmbeddingModel embeddingModel;  // BGE模型

        @Autowired
        private ChromaClient chromaClient;

        public List<SearchResult> search(String query, int topK) {
            // 1. 将查询转换为向量
            float[] queryVector = embeddingModel.embed(query);

            // 2. 在向量库中搜索最相似的文档
            return chromaClient.search(collection, queryVector, topK);
        }

        public void addDocument(Document doc) {
            // 1. 将文档转换为向量
            float[] vector = embeddingModel.embed(doc.getContent());

            // 2. 存入向量数据库
            chromaClient.add(collection, doc.getId(), vector, doc.getMetadata());
        }
    }
    ```

    【核心功能】
    1. add_documents(): 批量添加文档到向量库
    2. query(): 语义相似度检索
    3. delete(): 删除指定文档
    4. get_collection(): 获取或创建 Collection
    5. count(): 统计文档数量

    【Collection 说明】
    Collection 是 ChromaDB 中的逻辑容器，类似 MySQL 的 Table：
    - eight_part_qa: 八股文标准答案库
    - project_questions: 项目面试题库
    - scenario_cases: 场景设计案例库
    """

    DEFAULT_COLLECTION = "interview_knowledge"

    def __init__(self):
        settings = get_settings()

        self._persist_dir = settings.chromadb.persist_dir
        self._embedding_model_name = settings.chromadb.embedding_model
        self._top_k = settings.rag.top_k

        self._client = None
        self._collection = None
        self._embedding_function = None

        self._is_initialized = False

        self._initialize()

    def _initialize(self):
        """初始化 ChromaDB 客户端"""
        try:
            os.makedirs(self._persist_dir, exist_ok=True)

            self._client = chromadb.PersistentClient(
                path=self._persist_dir
            )

            logger.info(
                "chromadb_initialized",
                persist_dir=self._persist_dir,
                embedding_model=self._embedding_model_name
            )

            self._get_or_create_collection(self.DEFAULT_COLLECTION)
            self._is_initialized = True

        except Exception as e:
            logger.error("chromadb_init_failed", error=str(e))
            raise VectorDbError(f"ChromaDB初始化失败: {e}", detail=str(e))

    def _get_or_create_collection(
        self,
        collection_name: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        获取或创建 Collection

        【参数说明】
        - collection_name: 集合名称
        - metadata: 集合元数据（描述用途）

        【HNSW 索引说明】
        ChromaDB 默认使用 HNSW (Hierarchical Navigable Small World) 算法
        - 查询复杂度: O(log N)，非常高效
        - 适合内存中的向量检索
        - 支持动态增删文档
        """
        try:
            existing_collections = [c.name for c in self._client.list_collections()]

            if collection_name in existing_collections:
                self._collection = self._client.get_collection(name=collection_name)
                logger.info("chromadb_collection_loaded", name=collection_name)
            else:
                self._collection = self._client.create_collection(
                    name=collection_name,
                    metadata=metadata or {"description": "Interview knowledge base"}
                )
                logger.info(
                    "chromadb_collection_created",
                    name=collection_name,
                    space="cosine"
                )

        except Exception as e:
            logger.error(
                "chromadb_collection_error",
                name=collection_name,
                error=str(e)
            )
            raise VectorDbError(f"Collection操作失败: {e}", detail=str(e))

    def is_available(self) -> bool:
        """检查向量库是否可用"""
        return self._is_initialized and self._collection is not None

    async def add_documents(
        self,
        documents: List[Document],
        collection_name: Optional[str] = None
    ) -> int:
        """
        批量添加文档到向量库

        【参数说明】
        - documents: 文档列表
        - collection_name: 目标集合名（可选）

        【处理流程】
        1. 提取所有文档的 content 和 metadata
        2. 自动生成 ID（如果未提供）
        3. ChromaDB 内部调用 Embedding 模型生成向量
        4. 存入持久化存储

        【Java 类比】
        ```java
        // 类似 JPA 的 saveAll() 或 MyBatis 的 batch insert
        public int addDocuments(List<Document> docs) {
            List<String> ids = docs.stream()
                .map(d -> d.getId() != null ? d.getId() : UUID.randomUUID().toString())
                .collect(Collectors.toList());

            List<String> contents = docs.stream().map(Document::getContent).collect(Collectors.toList());
            List<Map<String, Object>> metadatas = docs.stream().map(Document::getMetadata).collect(Collectors.toList());

            collection.add(ids, embeddings, metadatas, contents);
            return docs.size();
        }
        ```

        【使用示例】
        docs = [
            Document(
                content="HashMap底层是数组+链表...",
                metadata={"category": "jvm", "difficulty": "medium"}
            ),
            Document(
                content="JVM内存结构包括堆、栈、方法区...",
                metadata={"category": "jvm", "difficulty": "easy"}
            )
        ]
        count = await store.add_documents(docs)
        """
        if not documents:
            return 0

        target_collection = self._get_target_collection(collection_name)

        try:
            ids = []
            contents = []
            metadatas = []

            for i, doc in enumerate(documents):
                doc_id = doc.id or f"doc_{i}_{hash(doc.content) % 10000}"
                ids.append(doc_id)
                contents.append(doc.content)
                metadatas.append(doc.metadata or {})

            target_collection.add(
                ids=ids,
                documents=contents,
                metadatas=metadatas
            )

            logger.info(
                "chromadb_add_documents",
                count=len(documents),
                collection=target_collection.name
            )

            return len(documents)

        except Exception as e:
            logger.error("chromadb_add_failed", error=str(e))
            raise VectorDbError(f"添加文档失败: {e}", detail=str(e))

    async def query(
        self,
        query_text: str,
        top_k: Optional[int] = None,
        where: Optional[Dict[str, Any]] = None,
        collection_name: Optional[str] = None
    ) -> List[SearchResult]:
        """
        语义相似度检索（RAG 核心！）

        【参数说明】
        - query_text: 用户的问题文本
        - top_k: 返回结果数量（默认配置值）
        - where: 过滤条件（按metadata筛选）
          例如: {"category": "jvm"} 只检索 JVM 相关内容
        - collection_name: 目标集合名

        【返回值】
        - List[SearchResult]: 相似度排序的结果列表

        【检索流程】
        1. 接收用户查询文本
        2. 使用 Embedding 模型将文本转换为向量 (1024维)
        3. 在向量空间中计算 cosine similarity
        4. 返回 Top-K 最相似的文档

        【Java 类比】
        ```java
        // 类似 Elasticsearch 的 vector search
        public List<SearchResult> search(String query, int topK) {
            float[] queryVector = embeddingModel.embed(query);

            SearchRequest request = SearchRequest.builder()
                .index("knowledge_base")
                .query(q -> q.scriptScore(ss -> ss.query(matchAll()).script(s ->
                    s.source("cosineSimilarity(params.query_vector, 'embedding') + 1.0")
                     .params("query_vector", queryVector)
                )))
                .size(topK)
                .build();

            return client.search(request);
        }
        ```

        【使用示例】
        # 基本搜索
        results = await store.query("HashMap底层实现")

        # 带过滤条件（只搜 JVM 相关）
        results = await store.query("内存模型", where={"category": "jvm"})

        # 使用不同集合
        results = await store.query("Spring Boot自动配置", collection_name="spring_questions")
        """
        if not query_text.strip():
            return []

        k = top_k or self._top_k
        target_collection = self._get_target_collection(collection_name)

        try:
            results = target_collection.query(
                query_texts=[query_text],
                n_results=k,
                where=where,
                include=["documents", "metadatas", "distances"]
            )

            search_results = []
            if results and results['ids'] and results['ids'][0]:
                for i, doc_id in enumerate(results['ids'][0]):
                    result = SearchResult(
                        id=doc_id,
                        content=results['documents'][0][i],
                        metadata=results['metadatas'][0][i] if results['metadatas'][0][i] else {},
                        distance=1 - results['distances'][0][i]
                    )
                    search_results.append(result)

            logger.info(
                "chromadb_query",
                query=query_text[:50],
                results_count=len(search_results),
                collection=target_collection.name
            )

            return search_results

        except Exception as e:
            logger.error("chromadb_query_failed", query=query_text[:50], error=str(e))
            raise VectorDbError(f"向量检索失败: {e}", detail=str(e))

    async def delete(
        self,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
        collection_name: Optional[str] = None
    ) -> bool:
        """删除文档"""
        if not ids and not where:
            return False

        target_collection = self._get_target_collection(collection_name)

        try:
            if ids:
                target_collection.delete(ids=ids)
            elif where:
                target_collection.delete(where=where)

            logger.info("chromadb_delete", ids_count=len(ids) if ids else 0)
            return True

        except Exception as e:
            logger.error("chromadb_delete_failed", error=str(e))
            return False

    async def count(self, collection_name: Optional[str] = None) -> int:
        """统计文档数量"""
        try:
            target_collection = self._get_target_collection(collection_name)
            return target_collection.count()
        except Exception as e:
            logger.error("chromadb_count_failed", error=str(e))
            return 0

    def _get_target_collection(self, collection_name: Optional[str]):
        """获取目标集合"""
        if collection_name and collection_name != self.DEFAULT_COLLECTION:
            collections = {c.name: c for c in self._client.list_collections()}
            if collection_name in collections:
                return collections[collection_name]
            else:
                self._get_or_create_collection(collection_name)
                return self._client.get_collection(name=collection_name)
        return self._collection

    def list_collections(self) -> List[str]:
        """列出所有集合名称"""
        if self._client:
            return [c.name for c in self._client.list_collections()]
        return []


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════

_vector_store_instance: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """获取全局向量数据库单例"""
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = VectorStore()
    return _vector_store_instance
