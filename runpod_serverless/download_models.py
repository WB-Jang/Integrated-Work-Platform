"""
Serverless 이미지 빌드 시 모델을 /models 에 미리 다운로드(굽기).
이렇게 하면 워커 cold start 시 모델 재다운로드가 없어 기동이 빠르다.
"""
import os

from huggingface_hub import snapshot_download

MODEL_DIR = os.environ.get("MODEL_DIR", "/models")

SKIP_PATTERNS = [
    "*.msgpack", "*.h5",
    "flax_model*", "tf_model*",
    "rust_model*",
    "onnx/*", "*.ot",
]


def _download(repo_id: str, subdir: str):
    target = os.path.join(MODEL_DIR, subdir)
    os.makedirs(target, exist_ok=True)
    print(f"[다운로드] {repo_id} → {target}")
    snapshot_download(
        repo_id=repo_id,
        local_dir=target,
        local_dir_use_symlinks=False,
        ignore_patterns=SKIP_PATTERNS,
    )
    print(f"[완료] {repo_id}")


if __name__ == "__main__":
    _download("BAAI/bge-m3", "bge-m3")
    _download("BAAI/bge-reranker-v2-m3", "bge-reranker")
    print("모든 모델 다운로드 완료")
