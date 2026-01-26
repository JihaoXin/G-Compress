#!/usr/bin/env python3
"""
AutoGAC Memory System - 极简版

功能：
1. 记录分数历史
2. 停滞检测
3. Goal Anchor

设计原则：信任 AI 的判断力，代码只做执行和保护
"""

import yaml
from datetime import datetime
from pathlib import Path
from typing import Tuple, List

MEMORY_FILE = Path(__file__).parent / "state" / "memory.yaml"

# 配置
STAGNATION_THRESHOLD = 5
MIN_PROGRESS_DELTA = 0.3

# Goal Anchor - 防止偏离大方向
GOAL_ANCHOR = """
## 论文核心目标 (Goal Anchor)

**论文标题**: When Smaller Is Slower: Dimensional Collapse in Compressed LLMs
**目标会议**: EuroMLSys 2025 (SIGPLAN format, 6 pages)

**核心贡献** (不可偏离):
1. 发现并量化 Dimensional Collapse 现象
2. 分析 GPU 性能悬崖的根本原因 (TC, Vec, BW, L2)
3. 提出 GAC 维度修复策略
4. 端到端验证修复效果

**关键约束**:
- 6 页限制（不含引用）
- 保持技术深度，不泛泛而谈
- 每个论点必须有数据支撑
"""


class SimpleMemory:
    """极简版迭代记忆 - 只追踪分数和停滞"""

    def __init__(self):
        self.scores: List[float] = []
        self.best_score: float = 0.0
        self.stagnation_count: int = 0
        self.load()

    def load(self):
        """从文件加载"""
        if MEMORY_FILE.exists():
            try:
                data = yaml.safe_load(MEMORY_FILE.read_text()) or {}
                self.scores = data.get("scores", [])
                self.best_score = data.get("best_score", 0.0)
                self.stagnation_count = data.get("stagnation_count", 0)
            except Exception:
                pass

    def save(self):
        """保存到文件"""
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_FILE.write_text(yaml.dump({
            "scores": self.scores[-20:],  # 只保留最近 20 个
            "best_score": self.best_score,
            "stagnation_count": self.stagnation_count,
            "last_updated": datetime.now().isoformat(),
        }, allow_unicode=True))

    def record_score(self, score: float):
        """记录新分数"""
        prev_score = self.scores[-1] if self.scores else 0.0
        self.scores.append(score)

        # 更新最高分
        if score > self.best_score:
            self.best_score = score

        # 停滞检测
        if (score - prev_score) >= MIN_PROGRESS_DELTA:
            self.stagnation_count = 0  # 有效进步，重置
        else:
            self.stagnation_count += 1

        self.save()

    def is_stagnating(self) -> Tuple[bool, str]:
        """检测是否停滞"""
        if self.stagnation_count >= STAGNATION_THRESHOLD:
            return True, f"连续 {self.stagnation_count} 次无有效进步 (delta < {MIN_PROGRESS_DELTA})"

        # 检查是否在原地打转
        if len(self.scores) >= 6:
            recent = self.scores[-6:]
            variance = max(recent) - min(recent)
            if variance < 0.5:
                return True, f"最近 6 次分数波动过小 ({variance:.2f})"

        return False, ""

    def get_context(self) -> str:
        """获取简单上下文（给 Agent 用）"""
        lines = [GOAL_ANCHOR, ""]

        # 停滞警告
        is_stuck, reason = self.is_stagnating()
        if is_stuck:
            lines.append(f"⚠️ **停滞警告**: {reason}")
            lines.append("建议：换一种完全不同的方法，或补充实验数据")
            lines.append("")

        # 分数趋势
        if self.scores:
            lines.append("## 分数趋势")
            lines.append(f"- 当前: **{self.scores[-1]}/10**")
            lines.append(f"- 最高: **{self.best_score}/10**")
            lines.append(f"- 历史: {' → '.join(f'{s:.1f}' for s in self.scores[-5:])}")
            lines.append("")

        return "\n".join(lines)

    def get_context_for_agent(self, agent_type: str) -> str:
        """兼容旧接口"""
        return self.get_context()

    def reset(self):
        """重置"""
        self.scores = []
        self.best_score = 0.0
        self.stagnation_count = 0
        self.save()


# 兼容旧接口的别名
IterationMemory = SimpleMemory

# 单例
_memory = None


def get_memory() -> SimpleMemory:
    """获取全局 Memory 实例"""
    global _memory
    if _memory is None:
        _memory = SimpleMemory()
    return _memory
