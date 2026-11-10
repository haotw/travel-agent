"""
第 07 章 · 一次性建库脚本
把 data/documents/destinations/ 下的 Markdown 文档处理进 Chroma

用法：
    uv run python scripts/Chapter_Seven/7_build_vectorstore.py

产物：
    data/vectorstore/    ← Chroma 持久化文件
"""
# Windows 事件循环兼容（虽然本脚本不用 psycopg，但保持一致）
import sys
import asyncio
import selectors

if sys.platform == "win32":
    selector = selectors.SelectSelector()
    loop = asyncio.SelectorEventLoop(selector)
    asyncio.set_event_loop(loop)
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.rag.document_loader import DocumentManager
from app.rag.text_splitter import AdvancedParentDocumentSplitter
from app.rag.vectorstore import VectorStoreManager


def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " 第 07 章 · 建库脚本".center(58) + "║")
    print("╚" + "═" * 58 + "╝")

    # 1. 加载文档
    print("\n▶ 步骤 1：加载 Markdown 文档")
    doc_manager = DocumentManager()
    documents = doc_manager.load_destination_documents()

    if not documents:
        print(
            "\n❌ 没找到任何目的地文档！\n"
            "请在 data/documents/destinations/ 下放至少一份 .md 攻略后再跑。\n"
        )
        return

    print(f"  ✅ 加载 {len(documents)} 份文档：")
    for doc in documents:
        print(f"    - {doc.metadata.get('source', '?')}")

    # 2. 父子分块
    print("\n▶ 步骤 2：父子分块")
    splitter = AdvancedParentDocumentSplitter(
        parent_chunk_size=1000,
        parent_chunk_overlap=200,
        child_chunk_size=200,
        child_chunk_overlap=50,
    )
    parent_docs, child_docs = splitter.split_documents(documents)
    print(f"  ✅ 父块 {len(parent_docs)} 个 / 子块 {len(child_docs)} 个")

    # 3. 建库（子块做 embedding + 存 Chroma）
    print("\n▶ 步骤 3：embedding + 存 Chroma（会调 DashScope API，稍等）")
    vs_manager = VectorStoreManager()
    vs_manager.create_vectorstore(child_docs)

    print("\n" + "🎉" * 20)
    print(f"  建库完成！")
    print(f"  向量库位置：data/vectorstore/")
    print(f"  下次运行 Agent 就能查询这些文档了")
    print("🎉" * 20 + "\n")


if __name__ == "__main__":
    main()