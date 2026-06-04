"""
임베딩 서버(bge-m3) + 리랭킹 서버(bge-reranker-v2-m3) 모델 다운로드 스크립트.

실행: python download_models.py
완료 후 models/bge-m3/ 와 models/bge-reranker/ 가 채워집니다.
"""
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
EMBED_PATH   = BASE_DIR / "models" / "bge-m3"
RERANK_PATH  = BASE_DIR / "models" / "bge-reranker"

# 건너뛸 파일 패턴 (TF/Flax/JAX/ONNX 가중치 — PyTorch만 사용)
SKIP_PATTERNS = [
    "*.msgpack", "*.h5",
    "flax_model*", "tf_model*",
    "rust_model*",
    "onnx/*", "*.ot",
]


def _is_empty(path: Path) -> bool:
    try:
        return not any(path.iterdir())
    except Exception:
        return True


def _download(repo_id: str, local_dir: Path, label: str):
    if not _is_empty(local_dir):
        print(f"[SKIP] {label} 이미 존재합니다: {local_dir}")
        return

    print(f"\n[{label}] 다운로드 시작 (repo: {repo_id})")
    print(f"         저장 경로: {local_dir}")
    local_dir.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import snapshot_download
        snapshot_download(
            repo_id=repo_id,
            local_dir=str(local_dir),
            local_dir_use_symlinks=False,
            ignore_patterns=SKIP_PATTERNS,
        )
        print(f"[OK] {label} 저장 완료")
    except ImportError:
        print("[!] huggingface_hub 미설치 → sentence_transformers 방식으로 fallback")
        _download_via_st(repo_id, local_dir, label)


def _download_via_st(repo_id: str, local_dir: Path, label: str):
    """huggingface_hub 없을 때 SentenceTransformer / CrossEncoder 경유 저장."""
    if "reranker" in repo_id.lower() or "rerank" in str(local_dir):
        from sentence_transformers import CrossEncoder
        m = CrossEncoder(repo_id)
        # CrossEncoder 내부 모델/토크나이저 직접 저장
        m.model.save_pretrained(str(local_dir))
        m.tokenizer.save_pretrained(str(local_dir))
    else:
        from sentence_transformers import SentenceTransformer
        m = SentenceTransformer(repo_id)
        m.save(str(local_dir))
    print(f"[OK] {label} 저장 완료 (ST 방식)")


def main():
    print("=" * 60)
    print("  IntegratedPlatform 모델 다운로드")
    print("=" * 60)
    print(f"  임베딩 모델 : BAAI/bge-m3          (~2.3 GB)")
    print(f"  리랭킹 모델 : BAAI/bge-reranker-v2-m3 (~570 MB)")
    print("  ※ 네트워크 속도에 따라 수 분 이상 소요될 수 있습니다.")
    print("=" * 60)

    t0 = time.time()

    _download(
        repo_id="BAAI/bge-m3",
        local_dir=EMBED_PATH,
        label="1/2  BGE-M3 (임베딩)",
    )

    _download(
        repo_id="BAAI/bge-reranker-v2-m3",
        local_dir=RERANK_PATH,
        label="2/2  BGE-Reranker-v2-M3 (리랭킹)",
    )

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  모든 모델 다운로드 완료  ({elapsed:.0f}초 소요)")
    print(f"  임베딩 서버 실행: python src/embedding_server.py")
    print(f"  리랭킹 서버 실행: python src/rerank_server.py")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
