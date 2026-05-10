"""
setup_test.py — 本地环境验证（不需要 API Key）
运行：python setup_test.py
"""

import os
import requests

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PASS = "[PASS]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"


def check(label, fn):
    try:
        result = fn()
        print(f"{PASS} {label}" + (f": {result}" if result else ""))
        return True
    except Exception as e:
        print(f"{FAIL} {label}: {e}")
        return False


# ── 1. Python 依赖 ──────────────────────────────────
print("\n=== 1. Python 依赖 ===")
check("chromadb", lambda: __import__("chromadb").__version__)
check("sentence_transformers", lambda: __import__("sentence_transformers").__version__)
check("anthropic", lambda: __import__("anthropic").__version__)
check("openai", lambda: __import__("openai").__version__)
check("python-dotenv", lambda: __import__("dotenv").__version__ if hasattr(__import__("dotenv"), "__version__") else "ok")
check("requests", lambda: __import__("requests").__version__)

# ── 2. RAG fallback embed ───────────────────────────
print("\n=== 2. RAG 轻量 fallback（不下载模型）===")
def test_embed():
    os.environ["NOVEL_RAG_MODE"] = "mock"
    from rag_engine import HashEmbeddingModel
    model = HashEmbeddingModel()
    vec = model.encode("测试文本")
    return f"向量维度={len(vec)}"

check("hash embedding 加载 + embed", test_embed)

# ── 3. ChromaDB 本地读写 ──────────────────────────────
print("\n=== 3. ChromaDB 本地存储 ===")
def test_chroma():
    import chromadb
    db_path = os.path.join(PROJECT_DIR, ".chromadb_test")
    client = chromadb.PersistentClient(path=db_path)
    col = client.get_or_create_collection("test")
    col.upsert(ids=["t1"], documents=["测试文档"], embeddings=[[0.1]*1536])
    result = col.get(ids=["t1"])
    client.delete_collection("test")
    import shutil
    shutil.rmtree(db_path, ignore_errors=True)
    return "写入/读取正常"

check("ChromaDB 持久化读写", test_chroma)

# ── 4. Ollama 连通性 ──────────────────────────────────
print("\n=== 4. Ollama 本地服务 ===")
def test_ollama_running():
    resp = requests.get("http://localhost:11434/api/tags", timeout=5)
    models = [m["name"] for m in resp.json().get("models", [])]
    return f"已加载模型：{models if models else '（拉取中，请等待）'}"

def test_ollama_generate():
    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "qwen3:8b",
            "prompt": "/no_think 请只输出两个字：通过",
            "stream": False,
            "options": {"num_predict": 8, "temperature": 0},
        },
        timeout=300,  # 冷启动需要时间
    )
    resp.raise_for_status()
    reply = resp.json()["response"][:50]
    return f"回复片段：{reply}…"

ollama_ok = check("Ollama 服务在线", test_ollama_running)
if ollama_ok:
    check("qwen3:8b 推理测试", test_ollama_generate)
else:
    print(f"{SKIP} qwen3:8b 推理测试（Ollama 未启动）")

# ── 5. 项目目录结构 ──────────────────────────────────
print("\n=== 5. 项目目录结构 ===")
required = [
    "00_世界观/角色档案",
    "01_大纲/章纲",
    "02_正文",
    "03_滚动记忆",
    "04_审核日志",
    "prompts",
    "prompts/正文生成.md",
    "prompts/逻辑审计.md",
    "prompts/摘要生成.md",
    "prompts/读者镜像.md",
    "prompts/深度检查.md",
    "rag_engine.py",
    "llm_router.py",
    "novel_pipeline.py",
    ".env.example",
]
all_ok = True
for rel in required:
    full = os.path.join(PROJECT_DIR, rel)
    exists = os.path.exists(full)
    status = PASS if exists else FAIL
    print(f"  {status} {rel}")
    if not exists:
        all_ok = False

# ── 6. .env 检查 ──────────────────────────────────────
print("\n=== 6. API Key 配置 ===")
env_path = os.path.join(PROJECT_DIR, ".env")
if os.path.isfile(env_path):
    with open(env_path, encoding="utf-8") as f:
        content = f.read()
    has_claude = "your-anthropic-key-here" not in content and "ANTHROPIC_API_KEY=" in content
    has_ds = "your-deepseek-key-here" not in content and "DEEPSEEK_API_KEY=" in content
    print(f"  {'[PASS]' if has_claude else '[待填]'} ANTHROPIC_API_KEY")
    print(f"  {'[PASS]' if has_ds else '[待填]'} DEEPSEEK_API_KEY")
else:
    print(f"  {FAIL} .env 文件不存在")

print("\n=== 完成 ===\n")
