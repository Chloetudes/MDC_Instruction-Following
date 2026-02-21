# -*- coding: utf-8 -*-
import os


class DirectoryManager:
    def __init__(self, base_dir: str = "outputs/evaluation"):
        self.base_dir = base_dir
        self.dirs = {
            "stage0_generation": f"{base_dir}/stage0_generation",
            "stage0.5_extraction": f"{base_dir}/stage0.5_extraction",
            "stage1_quality": f"{base_dir}/stage1_quality",
            "questions": f"{base_dir}/questions",
            "replies": f"{base_dir}/replies",
            "evaluations": f"{base_dir}/evaluations",
            "library": f"{base_dir}/library"
        }
        self._create_directories()

    def _create_directories(self):
        for dir_path in self.dirs.values():
            os.makedirs(dir_path, exist_ok=True)

    def get_path(self, stage: str, filename: str) -> str:
        if stage not in self.dirs:
            raise ValueError(f"未知的阶段: {stage}")
        return os.path.join(self.dirs[stage], filename)
