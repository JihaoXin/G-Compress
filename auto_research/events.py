#!/usr/bin/env python3
"""
AutoGAC Event System - 事件驱动调度

⚠️ DEPRECATED ⚠️
此模块已废弃，不再被 orchestrator.py 使用。
简化版架构改为让 Planner Agent 自主决策，不再使用事件驱动。
保留此文件仅供参考和回滚。

原功能：
1. 定义事件类型
2. 解析 Agent 输出中的触发标记
3. 根据事件自动路由到对应处理器
"""

import re
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Callable
from datetime import datetime


class EventType(Enum):
    """事件类型"""

    # === 系统事件 ===
    PAPER_NEEDS_REVIEW = "paper_needs_review"
    REVIEW_COMPLETED = "review_completed"
    LATEX_COMPILE_FAILED = "latex_compile_failed"
    LATEX_COMPILE_SUCCESS = "latex_compile_success"

    # === 质量事件 ===
    FIGURE_QUALITY_ISSUE = "figure_quality_issue"
    PAGE_LIMIT_EXCEEDED = "page_limit_exceeded"
    VISUAL_QUALITY_ISSUE = "visual_quality_issue"

    # === 实验事件 ===
    EXPERIMENT_NEEDED = "experiment_needed"
    EXPERIMENT_SUBMITTED = "experiment_submitted"
    EXPERIMENT_COMPLETED = "experiment_completed"
    EXPERIMENT_FAILED = "experiment_failed"

    # === 评分事件 ===
    SCORE_IMPROVED = "score_improved"
    SCORE_UNCHANGED = "score_unchanged"
    SCORE_REGRESSED = "score_regressed"
    SCORE_REACHED_THRESHOLD = "score_reached_threshold"

    # === Agent 触发的事件 ===
    REQUEST_FIGURE_FIX = "request_figure_fix"
    REQUEST_EXPERIMENT = "request_experiment"
    REQUEST_WRITING_FIX = "request_writing_fix"
    REQUEST_AGENT = "request_agent"


@dataclass
class Event:
    """事件对象"""
    type: EventType
    source: str  # 触发事件的来源（agent_type 或 "system"）
    data: dict   # 事件数据
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class EventParser:
    """解析 Agent 输出中的触发标记"""

    # 触发标记格式: [TRIGGER:TYPE] ... [/TRIGGER]
    TRIGGER_PATTERN = re.compile(
        r'\[TRIGGER:(\w+)\](.*?)\[/TRIGGER\]',
        re.DOTALL
    )

    # 简单关键词匹配（用于自动检测）
    KEYWORD_PATTERNS = {
        EventType.FIGURE_QUALITY_ISSUE: [
            r"图表.*?(?:字体|文字).*?(?:太小|不清|模糊|重叠)",
            r"figure.*?(?:font|text).*?(?:small|unclear|overlap)",
            r"图.*?(?:质量|问题)",
        ],
        EventType.PAGE_LIMIT_EXCEEDED: [
            r"超过.*?(?:6|六).*?页",
            r"page.*?(?:limit|exceed)",
            r"页数.*?超",
        ],
        EventType.EXPERIMENT_NEEDED: [
            r"需要.*?实验",
            r"add.*?experiment",
            r"perplexity.*?(?:验证|evaluation|missing)",
            r"缺少.*?(?:数据|实验|验证)",
        ],
        EventType.LATEX_COMPILE_FAILED: [
            r"编译.*?失败",
            r"compile.*?(?:fail|error)",
            r"latex.*?error",
        ],
    }

    # 触发标记名称到 EventType 的映射
    TRIGGER_TYPE_MAP = {
        "FIGURE_FIX": EventType.FIGURE_QUALITY_ISSUE,
        "FIGURE_QUALITY_ISSUE": EventType.FIGURE_QUALITY_ISSUE,
        "EXPERIMENT": EventType.EXPERIMENT_NEEDED,
        "EXPERIMENT_NEEDED": EventType.EXPERIMENT_NEEDED,
        "WRITING_FIX": EventType.REQUEST_WRITING_FIX,
        "PAGE_LIMIT": EventType.PAGE_LIMIT_EXCEEDED,
        "LATEX_ERROR": EventType.LATEX_COMPILE_FAILED,
        "REQUEST_AGENT": EventType.REQUEST_AGENT,
    }

    @classmethod
    def parse_triggers(cls, text: str, source: str = "unknown") -> list:
        """解析文本中的显式触发标记

        Args:
            text: Agent 输出文本
            source: 来源 agent 类型

        Returns:
            Event 列表
        """
        events = []
        for match in cls.TRIGGER_PATTERN.finditer(text):
            trigger_type = match.group(1).upper()
            content = match.group(2).strip()

            # 使用映射表转换触发类型
            if trigger_type in cls.TRIGGER_TYPE_MAP:
                event_type = cls.TRIGGER_TYPE_MAP[trigger_type]
            else:
                # 尝试直接映射到 EventType
                try:
                    event_type = EventType[trigger_type]
                except KeyError:
                    # 未知类型，使用 REQUEST_AGENT
                    event_type = EventType.REQUEST_AGENT

            events.append(Event(
                type=event_type,
                source=source,
                data={"content": content, "raw": match.group(0)}
            ))

        return events

    @classmethod
    def detect_events(cls, text: str, source: str = "unknown") -> list:
        """通过关键词自动检测事件

        Args:
            text: 文本内容
            source: 来源

        Returns:
            Event 列表
        """
        events = []
        text_lower = text.lower()

        for event_type, patterns in cls.KEYWORD_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    events.append(Event(
                        type=event_type,
                        source=source,
                        data={"detected_by": "keyword", "pattern": pattern}
                    ))
                    break  # 每种类型只触发一次

        return events


class EventRouter:
    """事件路由器 - 决定事件由谁处理"""

    # 事件 → 处理器映射
    # 格式: EventType -> [(agent_type, priority, condition)]
    HANDLERS = {
        EventType.FIGURE_QUALITY_ISSUE: [
            ("figure_fixer", 1, None),  # 优先触发图表修复
        ],
        EventType.PAGE_LIMIT_EXCEEDED: [
            ("writer", 1, None),  # Writer 压缩内容
        ],
        EventType.EXPERIMENT_NEEDED: [
            ("experimenter", 1, None),
            ("researcher", 2, None),  # 实验后分析
        ],
        EventType.LATEX_COMPILE_FAILED: [
            ("writer", 1, None),  # Writer 修复
        ],
        EventType.REVIEW_COMPLETED: [
            ("planner", 1, None),  # Planner 分析 review
        ],
        EventType.EXPERIMENT_COMPLETED: [
            ("researcher", 1, None),  # 分析结果
        ],
        EventType.REQUEST_AGENT: [
            # 动态决定，需要解析 data
        ],
    }

    @classmethod
    def route(cls, event: Event) -> list:
        """路由事件到处理器

        Args:
            event: 事件对象

        Returns:
            [(agent_type, task_description), ...] 列表
        """
        handlers = cls.HANDLERS.get(event.type, [])
        actions = []

        for agent_type, priority, condition in handlers:
            if condition is None or condition(event):
                task = cls._generate_task(event, agent_type)
                actions.append((agent_type, task, priority))

        # 按优先级排序
        actions.sort(key=lambda x: x[2])
        return [(a[0], a[1]) for a in actions]

    @classmethod
    def _generate_task(cls, event: Event, agent_type: str) -> str:
        """根据事件生成任务描述"""
        content = event.data.get("content", "")

        if event.type == EventType.FIGURE_QUALITY_ISSUE:
            return f"""检测到图表质量问题，请修复：

问题描述：
{content}

请修改 scripts/create_paper_figures.py 并重新生成图表。
确保：
1. 所有文字字体 >= 9pt
2. 无文字重叠
3. 图表比例合理（高度 >= 宽度 * 0.4）
"""

        elif event.type == EventType.PAGE_LIMIT_EXCEEDED:
            return f"""论文超过 6 页限制，请压缩内容：

建议：
1. 删除冗余描述
2. 合并相似的表格
3. 精简 Related Work
4. 将次要内容移到 Appendix

注意：不要删除核心贡献和关键实验数据。
"""

        elif event.type == EventType.EXPERIMENT_NEEDED:
            return f"""需要补充实验验证：

{content}

请设计并提交 Slurm 作业，确保：
1. 作业名称以 GAC_ 开头
2. 结果保存到 results/ 目录
3. 更新 findings.yaml
"""

        elif event.type == EventType.LATEX_COMPILE_FAILED:
            return f"""LaTeX 编译失败，请修复：

{content}

检查：
1. 语法错误（未闭合的括号、缺失的 \\end）
2. 引用错误（图表编号、引用）
3. 包依赖问题
"""

        else:
            return content or f"处理事件: {event.type.value}"


class EventQueue:
    """事件队列"""

    def __init__(self):
        self.queue = []
        self.processed = []

    def emit(self, event: Event):
        """发出事件"""
        self.queue.append(event)

    def emit_many(self, events: list):
        """批量发出事件"""
        self.queue.extend(events)

    def pop(self) -> Optional[Event]:
        """获取下一个待处理事件"""
        if self.queue:
            event = self.queue.pop(0)
            self.processed.append(event)
            return event
        return None

    def peek(self) -> Optional[Event]:
        """查看下一个事件但不移除"""
        return self.queue[0] if self.queue else None

    def is_empty(self) -> bool:
        return len(self.queue) == 0

    def clear(self):
        self.queue = []

    def get_pending_count(self) -> int:
        return len(self.queue)


# 全局事件队列
_event_queue = None


def get_event_queue() -> EventQueue:
    """获取全局事件队列"""
    global _event_queue
    if _event_queue is None:
        _event_queue = EventQueue()
    return _event_queue
