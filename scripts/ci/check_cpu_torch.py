"""Check that an environment has a CPU-only PyTorch build.

Run it with the Python of the environment to check:

    my-rag/.venv/bin/python scripts/ci/check_cpu_torch.py

Fails if torch is missing, was built with CUDA or ROCm, or if any nvidia-* or
triton distribution is installed. Imports torch but downloads nothing.
"""

import sys
from importlib.metadata import distributions


def check() -> list:
    problems = []
    try:
        import torch
    except ImportError as exc:
        return [f"torch is not installed: {exc}"]
    gpu_packages = sorted(
        d.metadata["Name"]
        for d in distributions()
        if d.metadata["Name"].lower().startswith(("nvidia-", "nvidia_", "triton"))
    )
    print(
        f"torch {torch.__version__}; built with CUDA: {torch.version.cuda}; "
        f"ROCm: {getattr(torch.version, 'hip', None)}; GPU packages: {gpu_packages or 'none'}"
    )
    if torch.version.cuda is not None:
        problems.append(f"torch was built with CUDA {torch.version.cuda}")
    if getattr(torch.version, "hip", None):
        problems.append(f"torch was built with ROCm {torch.version.hip}")
    if gpu_packages:
        problems.append(f"GPU packages are installed: {', '.join(gpu_packages)}")
    return problems


def main() -> int:
    problems = check()
    for problem in problems:
        print(f"FAIL {problem}")
    print("CPU-only PyTorch." if not problems else f"{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
