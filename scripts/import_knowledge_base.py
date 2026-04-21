"""
知识库导入脚本 - 从 PDF/Word 文档导入八股文到向量库

【使用方法】
1. 把你的 PDF/Word 八股文文档放到 knowledge_base/ 目录下
2. 运行: python scripts/import_knowledge_base.py
3. 脚本会自动解析文档并导入到 ChromaDB 向量库

【支持的文件格式】
- .pdf  → pdfplumber 解析（中文支持好）
- .docx → python-docx 解析

【文件命名规范】（用于自动识别分类）
- java_八股文.pdf        → 自动分类为 java
- mysql_面试题.pdf       → 自动分类为 mysql
- redis_缓存.docx        → 自动分类为 redis
- spring_框架.pdf        → 自动分类为 spring

【使用示例】
# 导入单个文件
python scripts/import_knowledge_base.py --file knowledge_base/java_八股文.pdf

# 导入整个目录
python scripts/import_knowledge_base.py --dir knowledge_base/

# 指定分类
python scripts/import_knowledge_base.py --file my_doc.pdf --category jvm

# 查看当前知识库状态
python scripts/import_knowledge_base.py --stats
"""

import asyncio
import argparse
import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

os.chdir(project_root)

from app.rag import get_rag_engine, RAGEngine
from app.infrastructure.logger import get_logger
from app.infrastructure.config import get_settings

logger = get_logger(__name__)


async def import_single_file(file_path: str, category: str = "general") -> int:
    """导入单个文件"""
    rag = get_rag_engine()
    
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return 0
    
    print(f"\n📄 正在解析: {file_path}")
    
    try:
        count = await rag.import_from_file(file_path, default_category=category)
        print(f"✅ 成功导入 {count} 条文档")
        return count
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        return 0


async def import_directory(directory: str, category: str = "general") -> dict:
    """导入整个目录"""
    rag = get_rag_engine()
    
    if not os.path.exists(directory):
        print(f"❌ 目录不存在: {directory}")
        return {}
    
    print(f"\n📁 正在扫描目录: {directory}")
    
    results = await rag.import_from_directory(directory, default_category=category)
    
    total = sum(results.values())
    print(f"\n📊 导入结果:")
    for file_path, count in results.items():
        status = "✅" if count > 0 else "⚠️"
        filename = Path(file_path).name
        print(f"   {status} {filename}: {count} 条")
    
    print(f"\n🎉 总计导入 {total} 条文档")
    return results


async def show_stats():
    """显示知识库状态"""
    rag = get_rag_engine()
    stats = await rag.get_stats()
    
    print("\n" + "=" * 50)
    print("📊 RAG 知识库状态")
    print("=" * 50)
    
    if stats.get("available"):
        doc_count = stats.get("document_count", 0)
        print(f"   ✅ RAG 引擎正常")
        print(f"   📚 已存储文档数: {doc_count}")
        
        settings = get_settings()
        persist_dir = settings.chromadb.persist_dir
        print(f"   💾 数据目录: {persist_dir}")
        
        if doc_count == 0:
            print("\n⚠️  知识库为空！请运行以下命令导入文档:")
            print("   python scripts/import_knowledge_base.py --dir knowledge_base/")
    else:
        error = stats.get("error", "未知错误")
        print(f"   ❌ RAG 引擎不可用: {error}")


async def test_search(query: str, category: str = None):
    """测试检索功能"""
    rag = get_rag_engine()
    
    if not rag.is_available():
        print("❌ RAG 引擎不可用")
        return
    
    print(f"\n🔍 测试检索: '{query}'")
    if category:
        print(f"   分类过滤: {category}")
    
    context = await rag.retrieve_for_scoring(
        question=query,
        answer="",
        category=category or "",
        top_k=5
    )
    
    if context:
        print("\n📖 检索结果:")
        print(context)
    else:
        print("⚠️  未找到相关内容，请先导入知识库")


def main():
    parser = argparse.ArgumentParser(
        description="AI Interview Agent - 知识库导入工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 导入单个文件
  python scripts/import_knowledge_base.py --file knowledge_base/java_八股文.pdf
  
  # 导入整个目录
  python scripts/import_knowledge_base.py --dir knowledge_base/
  
  # 查看知识库状态
  python scripts/import_knowledge_base.py --stats
  
  # 测试检索
  python scripts/import_knowledge_base.py --test "HashMap底层原理"
        """
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", "-f", help="导入单个文件 (PDF/DOCX)")
    group.add_argument("--dir", "-d", help="导入整个目录")
    group.add_argument("--stats", "-s", action="store_true", help="显示知识库状态")
    group.add_argument("--test", "-t", help="测试检索功能")
    
    parser.add_argument("--category", "-c", default="general",
                        help="指定文档分类 (java/mysql/redis/spring/...) [默认: general]")
    
    args = parser.parse_args()
    
    if args.file:
        asyncio.run(import_single_file(args.file, args.category))
    elif args.dir:
        asyncio.run(import_directory(args.dir, args.category))
    elif args.stats:
        asyncio.run(show_stats())
    elif args.test:
        asyncio.run(test_search(args.test))


if __name__ == "__main__":
    main()
