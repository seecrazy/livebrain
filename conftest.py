# 根目录 conftest：确保 pytest 将项目根加入 sys.path
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
