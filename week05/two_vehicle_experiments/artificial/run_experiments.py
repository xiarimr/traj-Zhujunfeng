"""人工前车速度场景的双车实验入口；三个模型统一定义在上级 common.py。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import main

if __name__ == "__main__":
    main()
