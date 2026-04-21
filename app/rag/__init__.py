# AI Interview Agent - RAG引擎层（向量检索增强）

from app.infrastructure.vector_store import VectorStore, Document, SearchResult
from app.tools.file_parser import FileParser
from app.infrastructure.logger import get_logger
from typing import List, Dict, Any, Optional, Tuple

logger = get_logger(__name__)

_rag_instance: Optional["RAGEngine"] = None


class RAGEngine:
    """
    RAG 检索增强引擎 - 统一封装向量库操作
    
    【职责】
    1. 管理向量库的初始化和生命周期
    2. 提供语义检索接口（给 ScoringSkill 调用）
    3. 提供知识库导入接口（从 PDF/Word 导入八股文）
    
    【使用场景】
    - 八股文评分前：检索参考答案，注入 Prompt 提升评分准确性
    - 项目启动时：导入预置知识库文档
    
    【Java 类比】
    ```java
    @Service
    public class RagService {
        @Autowired
        private VectorStore vectorStore;
        @Autowired
        private EmbeddingModel embeddingModel;
        
        public List<SearchResult> search(String query, String category) { ... }
        public void importDocuments(List<Document> docs) { ... }
    }
    ```
    """

    def __init__(self):
        self._vector_store: Optional[VectorStore] = None
        self._is_initialized = False

    def _ensure_initialized(self):
        """延迟初始化（首次调用时才连接 ChromaDB）"""
        if not self._is_initialized:
            try:
                self._vector_store = VectorStore()
                self._is_initialized = True
                logger.info("rag_engine_initialized")
            except Exception as e:
                logger.warning("rag_engine_init_failed", error=str(e))
                self._is_initialized = False

    def is_available(self) -> bool:
        """检查 RAG 是否可用"""
        self._ensure_initialized()
        return self._is_initialized and self._vector_store is not None and self._vector_store.is_available()

    async def retrieve_for_scoring(
        self,
        question: str,
        answer: str,
        category: str,
        top_k: int = 3
    ) -> str:
        """
        为评分检索相关参考资料（RAG 核心方法！）
        
        【调用时机】
        ScoringSkill 在调用 LLM 评分前，先调用此方法获取参考资料
        
        【检索策略】
        1. 用问题文本检索 Top-K 参考答案（找到标准答案）
        2. 用回答文本检索 Top-K 相关知识点（验证回答是否准确）
        3. 合并去重后返回
        
        【参数说明】
        - question: 面试题目（如"HashMap底层原理是什么？"）
        - answer: 候选人回答
        - category: 题目分类（如 jvm/mysql/redis/spring）
        - top_k: 返回结果数量（默认3条）
        
        【返回值】
        格式化好的参考文本字符串（可直接注入 Prompt）
        如果 RAG 不可用或无结果，返回空字符串
        
        【使用示例】
        rag = get_rag_engine()
        context = await rag.retrieve_for_scoring(
            question="HashMap底层原理？",
            answer="HashMap是数组加链表...",
            category="jvm"
        )
        # context = "【RAG 参考资料】\n- HashMap底层是数组+链表+红黑树..."
        """
        if not self.is_available():
            return ""

        all_results: List[SearchResult] = []
        
        # ═══ Step 1: 用题目检索标准答案 ═══
        try:
            question_results = await self._vector_store.query(
                query_text=question,
                top_k=top_k,
                where={"category": category} if category else None
            )
            all_results.extend(question_results)
            logger.debug(
                "rag_question_retrieval",
                question=question[:30],
                results_count=len(question_results)
            )
        except Exception as e:
            logger.warning("rag_query_failed", step="question", error=str(e))

        # ═══ Step 2: 用回答检索相关知识（交叉验证） ═══
        if answer and len(answer.strip()) > 10:
            try:
                answer_results = await self._vector_store.query(
                    query_text=answer,
                    top_k=max(1, top_k // 2),
                    where={"category": category} if category else None
                )
                
                # 去重（避免和 Step 1 结果重复）
                existing_ids = {r.id for r in all_results}
                for r in answer_results:
                    if r.id not in existing_ids:
                        all_results.append(r)
                        
                logger.debug(
                    "rag_answer_retrieval",
                    answer_preview=answer[:20],
                    results_count=len(answer_results)
                )
            except Exception as e:
                logger.warning("rag_query_failed", step="answer", error=str(e))

        # ═══ Step 3: 格式化输出 ═══
        if not all_results:
            return ""

        formatted = "\n【RAG 参考资料】\n"
        for i, result in enumerate(all_results, 1):
            meta_info = ""
            if result.metadata:
                cat = result.metadata.get("category", "")
                topic = result.metadata.get("topic", "")
                diff = result.metadata.get("difficulty", "")
                meta_info = f" [{cat}/{topic}/{diff}]" if (cat or topic or diff) else ""
            
            formatted += f"{i}. {result.content}{meta_info}\n"

        logger.info(
            "rag_retrieval_complete",
            total_references=len(all_results),
            context_length=len(formatted)
        )

        return formatted

    async def import_from_file(self, file_path: str, default_category: str = "general") -> int:
        """
        从 PDF/Word 文件导入知识库
        
        【参数说明】
        - file_path: 文件路径（支持 .pdf 和 .docx）
        - default_category: 默认分类（如果文件名没包含分类信息则用这个）
        
        【返回值】
        成功导入的文档数量
        
        【处理流程】
        1. 解析文件提取纯文本
        2. 按段落/问答对分割成独立文档
        3. 自动识别分类（从文件名或内容推断）
        4. 批量写入向量库
        """
        if not self.is_available():
            raise RuntimeError("RAG 引擎未初始化")

        parser = FileParser()
        parse_result = await parser.parse_file(file_path, extract_sections=False)

        if not parse_result.text or len(parse_result.text.strip()) < 50:
            logger.warning("file_content_too_short", file=file_path)
            return 0

        # 从文件名推断分类
        category = self._infer_category(file_path, default_category)

        # 分割文本为独立文档段
        documents = self._split_into_documents(
            text=parse_result.text,
            filename=parse_result.filename,
            file_type=parse_result.file_type,
            category=category
        )

        # 批量写入向量库
        count = await self._vector_store.add_documents(documents)

        logger.info(
            "rag_import_completed",
            file=file_path,
            category=category,
            documents_imported=count,
            original_chars=len(parse_result.text)
        )

        return count

    async def import_from_directory(
        self,
        directory: str,
        default_category: str = "general"
    ) -> Dict[str, int]:
        """
        批量导入目录下所有 PDF/Word 文件
        
        【返回值】
        {"文件路径": 导入数量, ...}
        """
        from pathlib import Path
        
        dir_path = Path(directory)
        if not dir_path.exists():
            raise FileNotFoundError(f"目录不存在: {directory}")

        results = {}
        for file_path in dir_path.glob("**/*"):
            if file_path.suffix.lower() in ('.pdf', '.docx'):
                try:
                    count = await self.import_from_file(str(file_path), default_category)
                    results[str(file_path)] = count
                except Exception as e:
                    logger.error("rag_import_file_failed", file=str(file_path), error=str(e))
                    results[str(file_path)] = 0

        total = sum(results.values())
        logger.info(
            "rag_batch_import_completed",
            directory=directory,
            files_processed=len(results),
            total_documents=total
        )

        return results

    def _infer_category(self, file_path: str, default: str) -> str:
        """从文件名推断分类"""
        filename_lower = file_path.lower()
        
        category_map = {
            'java': ['java', 'jvm', 'spring', 'mybatis', 'maven'],
            'mysql': ['mysql', '数据库', 'database', 'sql'],
            'redis': ['redis', '缓存', 'cache'],
            'spring': ['spring', 'boot', 'cloud'],
            'redis': ['redis', 'cache'],
            'network': ['网络', 'tcp', 'http', '协议'],
            'os': ['操作系统', 'os', 'linux', '线程', '进程'],
            'design_pattern': ['设计模式', 'pattern', '单例', '工厂'],
            'algorithm': ['算法', '数据结构', '排序', '二叉树'],
            'project': ['项目', '架构', '微服务', '分布式'],
        }

        for category, keywords in category_map.items():
            for kw in keywords:
                if kw in filename_lower:
                    return category

        return default

    def _split_into_documents(
        self,
        text: str,
        filename: str,
        file_type: str,
        category: str
    ) -> List[Document]:
        """
        将长文本分割为独立的文档段
        
        【分割策略】
        1. 尝试按"问：答："格式分割（适合 Q&A 文档）
        2. 按双换行符分割（按段落）
        3. 过滤太短或太长的段落
        4. 每个段落作为一个 Document
        """
        import re
        
        documents = []
        
        # 策略1：尝试按 Q&A 格式分割
        qa_pattern = re.compile(r'[问Q][：:]\s*(.+?)\s*[答A][：:]\s*(.+?)(?=[\n\r]*[问Q][：:]|\Z)', re.DOTALL)
        qa_matches = qa_pattern.findall(text)
        
        if qa_matches and len(qa_matches) >= 2:
            for q, a in qa_matches:
                content = f"问：{q.strip()}\n答：{a.strip()}"
                if len(content) >= 30:
                    topic = self._extract_topic(q + " " + a)
                    documents.append(Document(
                        content=content,
                        metadata={
                            "source": filename,
                            "category": category,
                            "type": "qa",
                            "topic": topic,
                            "char_count": len(content)
                        }
                    ))
        else:
            # 策略2：按段落分割
            paragraphs = re.split(r'\n\s*\n+', text.strip())
            for para in paragraphs:
                para = para.replace('\n', ' ').strip()
                if 30 <= len(para) <= 2000:
                    topic = self._extract_topic(para)
                    documents.append(Document(
                        content=para,
                        metadata={
                            "source": filename,
                            "category": category,
                            "type": "paragraph",
                            "topic": topic,
                            "char_count": len(para)
                        }
                    ))

        # 如果分割后没有有效文档，把整个文本作为一条
        if not documents and len(text) >= 30:
            documents.append(Document(
                content=text[:2000],
                metadata={
                    "source": filename,
                    "category": category,
                    "type": "full_document",
                    "topic": "",
                    "char_count": min(len(text), 2000)
                }
            ))

        return documents

    def _extract_topic(self, text: str) -> str:
        """从文本中提取主题关键词"""
        import re
        
        common_topics = [
            'HashMap', 'ArrayList', 'LinkedList', 'ConcurrentHashMap',
            'JVM', 'GC', '内存模型', '类加载',
            'Spring', 'IOC', 'AOP', '事务', 'Bean',
            'MySQL', '索引', 'B+树', '锁', '事务隔离',
            'Redis', '缓存穿透', '缓存击穿', '雪崩',
            'TCP', 'HTTP', 'HTTPS', 'WebSocket',
            '单例模式', '工厂模式', '观察者模式',
            '线程池', '死锁', 'volatile', 'synchronized'
        ]
        
        for topic in common_topics:
            if topic.lower() in text.lower():
                return topic
        
        return ""

    async def get_stats(self) -> Dict[str, Any]:
        """获取 RAG 引擎状态统计"""
        if not self.is_available():
            return {"available": False}

        try:
            count = await self._vector_store.count() if hasattr(self._vector_store, 'count') else 0
            return {
                "available": True,
                "document_count": count,
                "initialized": self._is_initialized
            }
        except Exception as e:
            return {"available": True, "error": str(e)}


def get_rag_engine() -> RAGEngine:
    """获取全局 RAG 引擎单例"""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = RAGEngine()
    return _rag_instance
