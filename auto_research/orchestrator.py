#!/usr/bin/env python3
"""
GAC (GPU-Aligned Compression) 全自动科研主控系统

运行方式:
    # 研究模式（实验 + 分析）
    python auto_research/orchestrator.py --mode research --max-days 3

    # 论文模式（审稿 + 改进）
    python auto_research/orchestrator.py --mode paper --max-iterations 10

    # 后台运行
    nohup python auto_research/orchestrator.py --mode paper --max-iterations 20 > auto_research/logs/orchestrator.log 2>&1 &

功能:
    研究模式 (research):
        1. 读取研究状态，决定下一步行动
        2. 调用专业 Agent 执行任务
        3. 等待 Slurm 作业完成
        4. 分析结果，更新状态
        5. 循环直到完成或超时

    论文模式 (paper):
        1. Reviewer Agent 审稿，给出评分和改进建议
        2. Writer Agent 根据建议改进论文
        3. 编译 LaTeX 验证
        4. 循环直到评分达标 (>= 8/10) 或达到最大迭代次数
"""

import argparse
import os
import subprocess
import sys
import time
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import re

# 项目根目录
PROJECT_DIR = Path(__file__).parent.parent.absolute()
os.chdir(PROJECT_DIR)

# 配置
STATE_FILE = PROJECT_DIR / "auto_research" / "state" / "research_state.yaml"
FINDINGS_FILE = PROJECT_DIR / "auto_research" / "state" / "findings.yaml"
PAPER_STATE_FILE = PROJECT_DIR / "auto_research" / "state" / "paper_state.yaml"
PAPER_REQUIREMENTS_FILE = PROJECT_DIR / "auto_research" / "state" / "paper_requirements.yaml"
LOG_DIR = PROJECT_DIR / "auto_research" / "logs"
AGENTS_DIR = PROJECT_DIR / "auto_research" / "agents"
LATEX_DIR = PROJECT_DIR / "Latex"
FIGURES_DIR = LATEX_DIR / "figures"

# 确保目录存在
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 论文审稿通过阈值
PAPER_ACCEPT_THRESHOLD = 8  # 总体评分 >= 8/10 则通过

# Checkpoint 文件
CHECKPOINT_FILE = PROJECT_DIR / "auto_research" / "state" / "checkpoint.yaml"

# Action Plan 文件（Planner 生成）
ACTION_PLAN_FILE = PROJECT_DIR / "auto_research" / "state" / "action_plan.yaml"


class Orchestrator:
    """主控调度器"""

    def __init__(self, max_days: float = 3, max_iterations: int = 100, mode: str = "research"):
        self.max_end_time = datetime.now() + timedelta(days=max_days)
        self.max_iterations = max_iterations
        self.iteration = 0
        self.mode = mode  # "research" or "paper"

        # 统一日志文件: AutoGAC_<mode>_<date>.log
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = LOG_DIR / f"AutoGAC_{mode}_{self.run_id}.log"

        # 启动时清理旧日志
        self._cleanup_old_logs(keep=5)

        # Token 使用统计
        self.total_input_tokens = 0
        self.total_output_tokens = 0

        # Rate limit 状态（防止重复通知）
        self._rate_limit_notified = False

    def save_checkpoint(self):
        """保存运行状态检查点"""
        checkpoint = {
            "run_id": self.run_id,
            "iteration": self.iteration,
            "mode": self.mode,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "timestamp": datetime.now().isoformat(),
        }
        with open(CHECKPOINT_FILE, "w") as f:
            yaml.dump(checkpoint, f, default_flow_style=False)
        self.log(f"Checkpoint saved: iteration={self.iteration}", "INFO")

    def load_checkpoint(self) -> dict:
        """加载检查点"""
        if CHECKPOINT_FILE.exists():
            with open(CHECKPOINT_FILE) as f:
                return yaml.safe_load(f) or {}
        return {}

    def resume_from_checkpoint(self):
        """从检查点恢复"""
        checkpoint = self.load_checkpoint()
        if checkpoint:
            self.iteration = checkpoint.get("iteration", 0)
            self.total_input_tokens = checkpoint.get("total_input_tokens", 0)
            self.total_output_tokens = checkpoint.get("total_output_tokens", 0)
            self.log(f"Resumed from checkpoint: iteration={self.iteration}", "INFO")
            return True
        return False

    def _parse_rate_limit_wait(self, error_msg: str) -> int:
        """从 rate limit 错误信息中解析等待时间（秒）

        支持格式：
        - "retry after 60 seconds"
        - "retry after 2026-01-25T14:30:00"
        - "reset at 1706188200" (Unix timestamp)
        - "wait 5 minutes"

        Returns:
            等待秒数，解析失败返回 300（默认 5 分钟）
        """
        import re
        from datetime import datetime

        error_lower = error_msg.lower()

        # 格式1: "retry after X seconds" 或 "wait X seconds"
        match = re.search(r"(?:retry after|wait)\s+(\d+)\s*(?:seconds?|s)", error_lower)
        if match:
            return int(match.group(1))

        # 格式2: "X minutes"
        match = re.search(r"(?:retry after|wait)\s+(\d+)\s*(?:minutes?|m)", error_lower)
        if match:
            return int(match.group(1)) * 60

        # 格式3: ISO 时间戳 "2026-01-25T14:30:00"
        match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", error_msg)
        if match:
            try:
                reset_time = datetime.fromisoformat(match.group(1))
                wait_seconds = (reset_time - datetime.now()).total_seconds()
                return max(int(wait_seconds), 60)  # 至少等 60 秒
            except ValueError:
                pass

        # 格式4: Unix timestamp
        match = re.search(r"reset.*?(\d{10})", error_lower)
        if match:
            try:
                reset_time = datetime.fromtimestamp(int(match.group(1)))
                wait_seconds = (reset_time - datetime.now()).total_seconds()
                return max(int(wait_seconds), 60)
            except (ValueError, OSError):
                pass

        # 默认：5 分钟
        return 300

    def _cleanup_old_logs(self, keep: int = 5):
        """清理旧日志文件，保留最近的 N 个"""
        # 清理 AutoGAC_*.log
        autogac_logs = sorted(LOG_DIR.glob("AutoGAC_*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        for old_log in autogac_logs[keep:]:
            old_log.unlink()

        # 清理旧的 agent_*.log 和 orchestrator_*.log（兼容旧格式）
        for pattern in ["agent_*.log", "orchestrator_*.log"]:
            old_logs = sorted(LOG_DIR.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
            for old_log in old_logs[keep:]:
                old_log.unlink()

    def _summarize_agent_output(self, agent_type: str, output: str) -> str:
        """生成 Agent 输出的摘要"""
        if not output or len(output) < 50:
            return ""

        summary_lines = []

        if agent_type == "reviewer":
            # 从 latest_review.md 读取关键信息
            review_file = PROJECT_DIR / "auto_research" / "state" / "latest_review.md"
            if review_file.exists():
                content = review_file.read_text()

                # 提取总评分
                score_match = re.search(r"\*\*Total\*\*.*?\*\*(\d+\.?\d*)/10\*\*", content, re.DOTALL)
                if score_match:
                    summary_lines.append(f"总评分: {score_match.group(1)}/10")

                # 提取 Rating 和 Confidence
                rating_match = re.search(r"\*\*Rating:\s*([^*\n]+)", content)
                if rating_match:
                    summary_lines.append(f"评级: {rating_match.group(1).strip()}")

                confidence_match = re.search(r"\*\*Confidence:\s*(\d+/\d+)", content)
                if confidence_match:
                    summary_lines.append(f"置信度: {confidence_match.group(1)}")

                # 提取各维度分数
                dimensions = [
                    ("Technical Quality", "技术"),
                    ("Paper Presentation", "呈现"),
                    ("Innovation", "创新"),
                    ("Writing Quality", "写作"),
                ]
                dim_scores = []
                for eng, chn in dimensions:
                    dim_match = re.search(rf"\|\s*{eng}\s*\|[^|]*\|\s*(\d+)/10", content)
                    if dim_match:
                        dim_scores.append(f"{chn}:{dim_match.group(1)}")
                if dim_scores:
                    summary_lines.append(f"分项: {' | '.join(dim_scores)}")

                # 提取 Major Issues 数量和标题
                major_issues = re.findall(r"### M\d+\.\s*([^\n]+)", content)
                if major_issues:
                    summary_lines.append(f"Major Issues ({len(major_issues)}个):")
                    for issue in major_issues[:3]:  # 最多显示3个
                        summary_lines.append(f"  - {issue.strip()}")
                    if len(major_issues) > 3:
                        summary_lines.append(f"  - ...还有 {len(major_issues) - 3} 个")

                # 提取 Minor Issues 数量
                minor_issues = re.findall(r"### m\d+\.\s*([^\n]+)", content)
                if minor_issues:
                    summary_lines.append(f"Minor Issues: {len(minor_issues)} 个")

                # 提取 Strengths 要点
                strengths_match = re.search(r"## Strengths\s*\n(.*?)(?=\n## |\n---|\Z)", content, re.DOTALL)
                if strengths_match:
                    strengths = re.findall(r"\d+\.\s*\*\*([^*]+)\*\*", strengths_match.group(1))
                    if strengths:
                        summary_lines.append(f"优点 ({len(strengths)}个): {', '.join(s.strip() for s in strengths[:4])}")

                # 提取 Weaknesses 要点
                weaknesses_match = re.search(r"## Weaknesses\s*\n(.*?)(?=\n## |\n---|\Z)", content, re.DOTALL)
                if weaknesses_match:
                    weaknesses = re.findall(r"\d+\.\s*\*\*([^*]+)\*\*", weaknesses_match.group(1))
                    if weaknesses:
                        summary_lines.append(f"缺点 ({len(weaknesses)}个): {', '.join(w.strip() for w in weaknesses[:4])}")

                # 提取 Recommendation
                rec_match = re.search(r"\*\*Recommendation:\*\*\s*([^\n]+)", content)
                if rec_match:
                    summary_lines.append(f"建议: {rec_match.group(1).strip()}")

        elif agent_type == "writer":
            # 从输出中提取修改信息
            edits = re.findall(r"(?:修改|更新|添加|删除|改进).*?(?:完成|成功)", output, re.IGNORECASE)
            if edits:
                summary_lines.append(f"修改操作: {len(edits)} 处")

            # 检查是否修改了 main.tex
            if "main.tex" in output.lower():
                summary_lines.append("修改了: Latex/main.tex")

            # 检查是否修改了图表
            fig_changes = re.findall(r"fig\d+|figure\s*\d+", output, re.IGNORECASE)
            if fig_changes:
                summary_lines.append(f"涉及图表: {len(set(fig_changes))} 个")

        elif agent_type == "validator":
            # 验证结果
            if "通过" in output or "pass" in output.lower():
                summary_lines.append("验证结果: 通过")
            elif "失败" in output or "fail" in output.lower():
                summary_lines.append("验证结果: 失败")
            else:
                summary_lines.append("验证结果: 待定")

        elif agent_type == "experimenter":
            # 实验信息
            slurm_jobs = re.findall(r"sbatch|srun|slurm", output, re.IGNORECASE)
            if slurm_jobs:
                summary_lines.append(f"提交 Slurm 作业: {len(slurm_jobs)} 个")

        # 通用：提取文件修改
        files_written = re.findall(r"(?:写入|保存|创建|Write|Save).*?([a-zA-Z0-9_/]+\.\w+)", output, re.IGNORECASE)
        if files_written:
            summary_lines.append(f"写入文件: {', '.join(set(files_written)[:5])}")

        return "\n".join(summary_lines) if summary_lines else "无明显变更"

    def cleanup_workspace(self):
        """清理工作区（LaTeX 临时文件、旧日志等）"""
        self.log("清理工作区...", "INFO")
        cleaned = 0

        # 1. 清理 LaTeX 临时文件
        latex_temp_exts = [".aux", ".log", ".out", ".toc", ".bbl", ".blg", ".fls", ".fdb_latexmk", ".synctex.gz"]
        for ext in latex_temp_exts:
            for f in LATEX_DIR.glob(f"*{ext}"):
                try:
                    f.unlink()
                    cleaned += 1
                except Exception:
                    pass

        # 2. 清理旧的 page_*.png（保留最新一批）
        page_images = sorted(LATEX_DIR.glob("page_*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
        for img in page_images[10:]:  # 保留最多 10 张
            try:
                img.unlink()
                cleaned += 1
            except Exception:
                pass

        # 3. 清理 Python 缓存
        for cache_dir in PROJECT_DIR.rglob("__pycache__"):
            if cache_dir.is_dir():
                try:
                    import shutil
                    shutil.rmtree(cache_dir)
                    cleaned += 1
                except Exception:
                    pass

        self.log(f"清理完成: 删除 {cleaned} 个临时文件", "INFO")

    def log(self, message: str, level: str = "INFO"):
        """记录日志，支持级别和实时刷新"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] [{level}] {message}"
        print(log_message, flush=True)
        with open(self.log_file, "a") as f:
            f.write(log_message + "\n")
            f.flush()  # 实时刷新到磁盘

    def load_state(self) -> dict:
        """加载研究状态"""
        with open(STATE_FILE) as f:
            return yaml.safe_load(f)

    def save_state(self, state: dict):
        """保存研究状态"""
        with open(STATE_FILE, "w") as f:
            yaml.dump(state, f, default_flow_style=False, allow_unicode=True)

    def get_current_phase(self, state: dict) -> str:
        """获取当前研究阶段"""
        phases = state.get("phases", {})
        for phase_name in ["C1_quantify", "C2_probe", "C3_formulate", "C4_solver", "C5_validation"]:
            phase = phases.get(phase_name, {})
            if phase.get("status") in ["pending", "in_progress"]:
                return phase_name
        return "completed"

    def run_agent(self, agent_type: str, task: str, timeout: int = 1800) -> str:
        """运行指定类型的 Agent，输出写入统一日志"""
        import json

        prompt_file = AGENTS_DIR / f"{agent_type}.prompt"
        if not prompt_file.exists():
            self.log(f"Agent prompt not found: {prompt_file}", "ERROR")
            return ""

        base_prompt = prompt_file.read_text()

        full_prompt = f"""{base_prompt}

---

## 当前任务

{task}

## 上下文文件

请阅读以下文件获取上下文（如果存在）：
- auto_research/state/research_state.yaml - 当前研究状态
- auto_research/state/findings.yaml - 已有发现
- report.md - 研究报告
- results/ 目录 - 实验结果

执行任务并更新相应文件。
"""

        self.log(f">>> Agent [{agent_type}] 开始: {task[:80]}...", "AGENT")

        try:
            # 使用 stream-json 获取详细输出和 token 统计
            # 注意：stream-json 需要 --verbose 参数
            process = subprocess.Popen(
                [
                    "claude", "-p", full_prompt,
                    "--dangerously-skip-permissions",
                    "--output-format", "stream-json",
                    "--verbose",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=PROJECT_DIR,
                bufsize=1,
            )

            output_text = []
            start_time = time.time()
            token_info = {}

            while True:
                # 检查超时
                if time.time() - start_time > timeout:
                    process.kill()
                    self.log(f"Agent {agent_type} 超时 ({timeout}s)", "WARN")
                    break

                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    continue

                # 解析 JSON 流
                try:
                    data = json.loads(line.strip())
                    msg_type = data.get("type", "")

                    if msg_type == "assistant":
                        # 提取文本内容
                        content = data.get("message", {}).get("content", [])
                        for item in content:
                            if item.get("type") == "text":
                                text = item.get("text", "")
                                if text:
                                    output_text.append(text)
                                    # 只打印关键信息到日志
                                    if len(text) < 300:
                                        self.log(f"  [{agent_type}] {text[:200]}", "AGENT")

                    elif msg_type == "result":
                        # 提取 token 使用情况
                        usage = data.get("usage", {})
                        token_info = {
                            "input": usage.get("input_tokens", 0),
                            "output": usage.get("output_tokens", 0),
                        }
                        result_text = data.get("result", "")
                        if result_text:
                            output_text.append(result_text)

                except json.JSONDecodeError:
                    # 非 JSON 行，检查是否是错误信息
                    line_stripped = line.strip()
                    if line_stripped:
                        self.log(f"  [{agent_type}] {line_stripped[:150]}", "AGENT")

                        # 检测 rate limit 错误
                        if "rate limit" in line_stripped.lower() or "rate_limit" in line_stripped.lower():
                            wait_seconds = self._parse_rate_limit_wait(line_stripped)
                            wait_minutes = wait_seconds / 60

                            self.log(f"检测到 Rate Limit: 需等待 {wait_minutes:.1f} 分钟", "WARN")

                            # 只在首次触发时发邮件
                            if not self._rate_limit_notified:
                                self._rate_limit_notified = True
                                self.save_checkpoint()
                                self.send_notification(
                                    f"Rate Limit - 等待 {wait_minutes:.0f} 分钟",
                                    f"Agent {agent_type} 触发 rate limit。\n"
                                    f"等待时间: {wait_minutes:.1f} 分钟\n"
                                    f"预计恢复: {(datetime.now() + timedelta(seconds=wait_seconds)).strftime('%H:%M:%S')}\n"
                                    f"系统将自动等待后恢复。",
                                    priority="critical"
                                )

                            # 动态等待
                            self.log(f"等待 {wait_minutes:.1f} 分钟后自动恢复...", "INFO")
                            time.sleep(wait_seconds + 10)  # 多等 10 秒确保恢复
                            self._rate_limit_notified = False  # 重置状态

            # 更新 token 统计
            if token_info:
                self.total_input_tokens += token_info.get("input", 0)
                self.total_output_tokens += token_info.get("output", 0)
                self.log(f"<<< Agent [{agent_type}] 完成 | Token: in={token_info['input']}, out={token_info['output']} | 累计: in={self.total_input_tokens:,}, out={self.total_output_tokens:,}", "AGENT")
            else:
                self.log(f"<<< Agent [{agent_type}] 完成", "AGENT")

            result = "\n".join(output_text)

            # 生成并打印 Agent 摘要
            summary = self._summarize_agent_output(agent_type, result)
            if summary:
                self.log(f"--- [{agent_type}] 摘要 ---", "SUMMARY")
                for line in summary.split("\n"):
                    if line.strip():
                        self.log(f"  {line}", "SUMMARY")
                self.log(f"--- 摘要结束 ---", "SUMMARY")

            return result

        except Exception as e:
            self.log(f"Agent {agent_type} 错误: {e}", "ERROR")
            self.send_notification("Agent 错误", f"Agent {agent_type} 发生错误: {e}", priority="critical")
            return ""

    def wait_for_slurm(self, max_wait_hours: float = 4) -> bool:
        """等待所有 Slurm 作业完成"""
        self.log("Checking Slurm jobs...")
        max_wait = timedelta(hours=max_wait_hours)
        start_time = datetime.now()

        while datetime.now() - start_time < max_wait:
            try:
                result = subprocess.run(
                    ["squeue", "-u", os.environ.get("USER", "xinj"), "-h"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                running_jobs = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0

                if running_jobs == 0:
                    self.log("All Slurm jobs completed")
                    return True

                self.log(f"{running_jobs} jobs still running, waiting 60s...")
                time.sleep(60)

            except Exception as e:
                self.log(f"Error checking Slurm: {e}")
                time.sleep(60)

        self.log(f"Slurm wait timeout after {max_wait_hours} hours")
        return False

    def git_commit(self, message: str, files: list = None):
        """在关键节点自动 git commit

        Args:
            message: commit 消息
            files: 要提交的文件列表，None 表示所有更改
        """
        try:
            # 先检查是否有更改
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, cwd=PROJECT_DIR, timeout=30
            )

            if not status_result.stdout.strip():
                self.log("Git: 没有更改需要提交", "INFO")
                return False

            # 添加文件
            if files:
                for f in files:
                    subprocess.run(["git", "add", f], cwd=PROJECT_DIR, timeout=30)
            else:
                # 添加关键文件（排除临时文件）
                key_files = [
                    "Latex/main.tex",
                    "report.md",
                    "auto_research/state/*.yaml",
                    "auto_research/state/*.md",
                ]
                for pattern in key_files:
                    subprocess.run(
                        ["git", "add", pattern],
                        cwd=PROJECT_DIR, timeout=30,
                        capture_output=True  # 忽略不存在的文件警告
                    )

            # 提交
            commit_msg = f"[AutoGAC] {message}\n\nIteration: {self.iteration}\nScore: {getattr(self, '_last_score', 'N/A')}"
            result = subprocess.run(
                ["git", "commit", "-m", commit_msg],
                capture_output=True, text=True, cwd=PROJECT_DIR, timeout=60
            )

            if result.returncode == 0:
                self.log(f"Git commit: {message}", "INFO")
                return True
            else:
                self.log(f"Git commit 失败: {result.stderr[:200]}", "WARN")
                return False

        except Exception as e:
            self.log(f"Git commit 错误: {e}", "ERROR")
            return False

    def send_notification(self, subject: str, message: str, priority: str = "normal"):
        """发送邮件通知

        Args:
            subject: 邮件主题
            message: 邮件内容
            priority: 优先级 ("normal", "critical")
        """
        # 关键词触发邮件通知
        critical_keywords = ["error", "failed", "token", "accepted", "completed", "timeout"]
        should_send = priority == "critical" or any(kw in subject.lower() for kw in critical_keywords)

        if not should_send:
            self.log(f"Notification skipped (non-critical): {subject}", "INFO")
            return

        try:
            email = "jihao.xin@kaust.edu.sa"
            # 添加状态摘要
            full_message = f"""{message}

---
AutoGAC Status:
- Run ID: {self.run_id}
- Mode: {self.mode}
- Iteration: {self.iteration}
- Total Tokens: in={self.total_input_tokens:,}, out={self.total_output_tokens:,}
- Log: {self.log_file}
"""
            subprocess.run(
                ["mail", "-s", f"[AutoGAC] {subject}", email],
                input=full_message,
                text=True,
                timeout=30,
            )
            self.log(f"Notification sent: {subject}", "INFO")
        except Exception as e:
            self.log(f"Failed to send notification: {e}", "WARN")

    def compile_latex(self) -> bool:
        """编译 LaTeX 论文"""
        self.log("Compiling LaTeX...")
        try:
            # 运行 pdflatex + bibtex + pdflatex x2
            for cmd in [
                ["pdflatex", "-interaction=nonstopmode", "main.tex"],
                ["bibtex", "main"],
                ["pdflatex", "-interaction=nonstopmode", "main.tex"],
                ["pdflatex", "-interaction=nonstopmode", "main.tex"],
            ]:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=LATEX_DIR,
                )
                if result.returncode != 0 and "main.tex" in cmd:
                    self.log(f"LaTeX compilation warning: {result.stderr[:500]}")

            # 检查 PDF 是否生成
            pdf_path = LATEX_DIR / "main.pdf"
            if pdf_path.exists():
                self.log(f"LaTeX compiled successfully: {pdf_path}")
                return True
            else:
                self.log("LaTeX compilation failed: PDF not generated")
                return False
        except Exception as e:
            self.log(f"LaTeX compilation error: {e}")
            return False

    def load_paper_state(self) -> dict:
        """加载论文审稿状态"""
        if PAPER_STATE_FILE.exists():
            with open(PAPER_STATE_FILE) as f:
                return yaml.safe_load(f) or {}
        return {
            "reviews": [],
            "current_score": 0,
            "status": "in_progress",
        }

    def load_paper_requirements(self) -> dict:
        """加载论文需求配置"""
        if PAPER_REQUIREMENTS_FILE.exists():
            with open(PAPER_REQUIREMENTS_FILE) as f:
                return yaml.safe_load(f) or {}
        return {}

    def _generate_figures_from_results(self) -> bool:
        """从最新实验结果生成图表并复制到论文目录"""
        self.log(">>> 从实验结果生成新图表...", "FIGURES")
        try:
            import glob
            import shutil

            # 找最新的实验结果目录
            result_dirs = []
            for exp_type in ["llm", "perplexity_validation", "gemm", "sdpa"]:
                pattern = str(PROJECT_DIR / f"results/{exp_type}/*")
                dirs = glob.glob(pattern)
                result_dirs.extend(dirs)

            if not result_dirs:
                self.log("  没有找到新实验结果", "FIGURES")
                return False

            # 按修改时间排序，取最新的
            result_dirs.sort(key=lambda x: Path(x).stat().st_mtime if Path(x).is_dir() else 0, reverse=True)
            latest_result = Path(result_dirs[0])

            self.log(f"  最新结果: {latest_result}", "FIGURES")

            # 尝试运行对应的图表生成脚本
            if "llm" in str(latest_result):
                cmd = f"python -m scripts.plot_llm_results {latest_result.parent}"
            else:
                cmd = f"python -m scripts.plot_results {latest_result}"

            self.log(f"  运行: {cmd}", "FIGURES")
            result = subprocess.run(
                ["bash", "-c", f"source ~/.bashrc && mamba activate gc && {cmd}"],
                capture_output=True, text=True, timeout=300, cwd=PROJECT_DIR
            )

            if result.returncode != 0:
                self.log(f"  图表生成警告: {result.stderr[:200]}", "WARN")

            # 复制新生成的图表到 Latex/figures/
            plots_dir = latest_result / "plots"
            if plots_dir.exists():
                for pdf in plots_dir.glob("*.pdf"):
                    dest = FIGURES_DIR / pdf.name
                    shutil.copy(pdf, dest)
                    self.log(f"  复制图表: {pdf.name} -> Latex/figures/", "FIGURES")

            return True

        except Exception as e:
            self.log(f"  图表生成错误: {e}", "ERROR")
            return False

    def generate_figures(self) -> bool:
        """运行图表生成脚本"""
        self.log("Generating paper figures...", "INFO")
        try:
            # 确保 figures 目录存在
            FIGURES_DIR.mkdir(parents=True, exist_ok=True)

            result = subprocess.run(
                ["bash", "-c", "source ~/.bashrc && mamba activate gc && python scripts/create_paper_figures.py"],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=PROJECT_DIR,
            )

            if result.returncode == 0:
                self.log("Figure generation completed successfully", "INFO")
                return True
            else:
                self.log(f"Figure generation warning: {result.stderr[:500]}", "WARN")
                return True  # 继续，即使有警告
        except Exception as e:
            self.log(f"Figure generation error: {e}", "ERROR")
            return False

    def pdf_to_images(self) -> list:
        """将 PDF 转换为图像用于视觉审核"""
        self.log("Converting PDF to images for visual review...", "INFO")
        try:
            result = subprocess.run(
                ["bash", "-c", "source ~/.bashrc && mamba activate gc && python scripts/pdf_to_images.py Latex/main.pdf --dpi 150"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=PROJECT_DIR,
            )

            if result.returncode == 0:
                # 获取生成的图像列表
                images = list(LATEX_DIR.glob("page_*.png"))
                self.log(f"Generated {len(images)} page images", "INFO")
                return [str(img) for img in sorted(images)]
            else:
                self.log(f"PDF to images warning: {result.stderr[:200]}", "WARN")
                return []
        except Exception as e:
            self.log(f"PDF to images error: {e}", "ERROR")
            return []

    def save_paper_state(self, state: dict):
        """保存论文审稿状态"""
        with open(PAPER_STATE_FILE, "w") as f:
            yaml.dump(state, f, default_flow_style=False, allow_unicode=True)

    def _load_action_plan(self) -> dict:
        """加载 Planner 生成的 action plan"""
        if ACTION_PLAN_FILE.exists():
            with open(ACTION_PLAN_FILE) as f:
                return yaml.safe_load(f) or {}
        return {"issues": []}

    def _save_action_plan(self, action_plan: dict):
        """保存 action plan"""
        with open(ACTION_PLAN_FILE, "w") as f:
            yaml.dump(action_plan, f, default_flow_style=False, allow_unicode=True)

    def _load_findings_summary(self) -> str:
        """加载 findings.yaml 的摘要"""
        if FINDINGS_FILE.exists():
            with open(FINDINGS_FILE) as f:
                findings = yaml.safe_load(f) or {}
            # 返回摘要（前 500 字符）
            return yaml.dump(findings, allow_unicode=True)[:500]
        return "暂无 findings"

    def _wait_for_slurm_jobs(self, max_wait_hours: float = 2) -> bool:
        """等待 Slurm 作业完成（内部使用的简化版本）"""
        return self.wait_for_slurm(max_wait_hours=max_wait_hours)

    def parse_review_score(self, review_output: str) -> float:
        """从审稿输出中解析总体评分"""
        # 支持多种格式：
        # 1. "总体评分: 7/10" 或 "Overall Score: 7/10"
        # 2. "| **Total** | 100% | - | **7.5/10** |" (表格格式)
        # 3. 任意 "X/10" 或 "X.X/10"
        patterns = [
            r"总体评分[：:]\s*(\d+\.?\d*)/10",
            r"Overall Score[：:]\s*(\d+\.?\d*)/10",
            r"总分[：:]\s*(\d+\.?\d*)/10",
            r"\*\*Total\*\*.*?\*\*(\d+\.?\d*)/10\*\*",  # 表格 Markdown 格式
            r"\|\s*Total\s*\|.*?(\d+\.?\d*)/10",       # 简化表格格式
        ]
        for pattern in patterns:
            match = re.search(pattern, review_output, re.IGNORECASE | re.DOTALL)
            if match:
                score = float(match.group(1))
                self.log(f"解析到评分: {score}/10")
                return score

        # 兜底：从 latest_review.md 文件读取
        review_file = PROJECT_DIR / "auto_research" / "state" / "latest_review.md"
        if review_file.exists():
            content = review_file.read_text()
            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                if match:
                    score = float(match.group(1))
                    self.log(f"从 latest_review.md 解析到评分: {score}/10")
                    return score

        self.log("警告: 未能解析到评分，返回 0")
        return 0.0

    def _check_needs_experiment(self, review_output: str) -> bool:
        """分析审稿意见，判断是否需要补充实验

        检测关键词：
        - "需要补充实验" / "add experiment"
        - "缺少数据" / "missing data"
        - "验证不足" / "insufficient validation"
        - "建议增加" / "suggest adding"
        """
        # 也检查 latest_review.md 文件
        review_file = PROJECT_DIR / "auto_research" / "state" / "latest_review.md"
        content = review_output
        if review_file.exists():
            content += "\n" + review_file.read_text()

        # 实验相关关键词
        experiment_keywords = [
            r"需要.*实验",
            r"补充.*实验",
            r"缺少.*数据",
            r"验证不足",
            r"建议.*增加.*实验",
            r"add.*experiment",
            r"missing.*data",
            r"insufficient.*validation",
            r"suggest.*adding.*experiment",
            r"need.*more.*evidence",
            r"require.*additional.*test",
        ]

        for pattern in experiment_keywords:
            if re.search(pattern, content, re.IGNORECASE):
                self.log(f"检测到实验需求关键词: {pattern}", "INFO")
                return True

        return False

    def run_planner_cycle(self, review_output: str) -> bool:
        """Planner 驱动的迭代循环

        流程:
        1. Planner 分析 review，生成 action_plan.yaml
        2. 执行所有实验类任务（inner loop）
        3. 所有实验完成后，执行写作任务

        Args:
            review_output: Reviewer 的输出

        Returns:
            True 如果成功完成
        """
        import json

        # Step 1: Planner 分析 review，生成 action plan
        self.log(">>> Planner 分析审稿意见...", "PLANNER")
        findings_summary = self._load_findings_summary()

        planner_output = self.run_agent("planner", f"""
分析以下审稿意见，生成 action_plan.yaml。

## 审稿意见摘要
请读取完整审稿报告：auto_research/state/latest_review.md

## 当前 Findings 摘要
{findings_summary}

## 任务
1. 识别所有 Major Issues (M1, M2, ...) 和 Minor Issues (m1, m2, ...)
2. 对每个 issue 分类：EXPERIMENT_REQUIRED 或 WRITING_ONLY
3. 为每个 issue 生成具体的 action 列表
4. 将结果写入 auto_research/state/action_plan.yaml

注意：
- EXPERIMENT_REQUIRED: 需要跑 GPU 实验（如添加 perplexity 测量、补充 benchmark）
- WRITING_ONLY: 只需修改文字、图表、格式等
""", timeout=1200)

        # Step 2: 加载生成的 action plan
        action_plan = self._load_action_plan()
        issues = action_plan.get("issues", [])

        if not issues:
            self.log("警告: Planner 未生成 issues，跳过 planner cycle", "WARN")
            return False

        self.log(f"Planner 生成了 {len(issues)} 个 issues:", "PLANNER")
        exp_count = sum(1 for i in issues if i.get("type") == "EXPERIMENT_REQUIRED")
        write_count = sum(1 for i in issues if i.get("type") == "WRITING_ONLY")
        self.log(f"  - EXPERIMENT_REQUIRED: {exp_count}", "PLANNER")
        self.log(f"  - WRITING_ONLY: {write_count}", "PLANNER")

        # Step 3: 执行实验类任务（inner loop）
        for issue in issues:
            if issue.get("type") == "EXPERIMENT_REQUIRED" and issue.get("status", "pending") == "pending":
                self.log(f">>> 处理实验任务: {issue.get('id')} - {issue.get('title')}", "PLANNER")
                self._run_experiment_inner_loop(issue, action_plan)

        # Step 4: 检查所有实验是否完成
        all_experiments_done = all(
            issue.get("status") in ["completed", "failed", "skipped"]
            for issue in issues
            if issue.get("type") == "EXPERIMENT_REQUIRED"
        )

        if all_experiments_done:
            self.log(">>> 实验阶段完成，进入写作阶段...", "PLANNER")
            self._run_writing_phase(action_plan)
            return True

        self.log("警告: 部分实验未完成", "WARN")
        return False

    def _run_experiment_inner_loop(self, issue: dict, action_plan: dict):
        """执行单个实验类 issue 的内部迭代

        流程:
        1. Experimenter 设计并运行实验
        2. 等待 Slurm 作业完成
        3. Researcher 分析结果
        4. Planner 评估是否满意
        5. 如果不满意且未超过最大迭代次数，重复

        Args:
            issue: issue 字典
            action_plan: 完整的 action plan（用于保存状态）
        """
        import json

        max_loops = issue.get("max_inner_loops", 3)
        issue["inner_loop_count"] = issue.get("inner_loop_count", 0)
        issue["status"] = "in_progress"
        self._save_action_plan(action_plan)

        # 获取 experimenter 任务
        exp_task = issue.get("description", issue.get("title", "未知任务"))
        actions = issue.get("actions", [])
        if actions:
            for action in actions:
                if action.get("agent") == "experimenter":
                    exp_task = action.get("task", exp_task)
                    break

        while issue["inner_loop_count"] < max_loops:
            issue["inner_loop_count"] += 1
            loop_num = issue["inner_loop_count"]
            self.log(f">>> Inner Loop #{loop_num}/{max_loops} for {issue.get('id')}", "INNERLOOP")

            # 1. Experimenter 设计并运行实验
            self.log(f"  [Experimenter] {exp_task[:80]}...", "INNERLOOP")
            exp_output = self.run_agent("experimenter", f"""
任务: {exp_task}

Issue 背景:
- ID: {issue.get('id')}
- 标题: {issue.get('title')}
- 描述: {issue.get('description', 'N/A')}

这是 Inner Loop 第 {loop_num} 次尝试（最多 {max_loops} 次）。
请设计并提交实验，使用 Slurm 运行 GPU 任务。
""", timeout=1800)

            # 2. 等待 Slurm 作业完成
            self.log("  [等待 Slurm 作业完成...]", "INNERLOOP")
            self._wait_for_slurm_jobs(max_wait_hours=2)

            # 3. Researcher 分析结果
            self.log("  [Researcher] 分析实验结果...", "INNERLOOP")
            research_output = self.run_agent("researcher", f"""
分析实验结果，判断是否满足审稿要求。

Issue: {issue.get('id')} - {issue.get('title')}
任务: {exp_task}

请检查:
1. 实验是否成功完成（无 OOM、无错误）
2. 结果文件是否生成
3. 数据是否支持论文论点
4. 更新 findings.yaml 记录新发现

给出明确结论：实验是否满足要求。
""", timeout=1200)

            # 4. Planner 评估是否满意
            self.log("  [Planner] 评估 Inner Loop 结果...", "INNERLOOP")
            eval_output = self.run_agent("planner", f"""
评估 Inner Loop 结果，判断是否可以进入下一阶段。

## Issue 信息
- ID: {issue.get('id')}
- 标题: {issue.get('title')}
- 当前尝试: {loop_num}/{max_loops}

## Experimenter 输出摘要
{exp_output[:800] if exp_output else '无输出'}

## Researcher 分析摘要
{research_output[:800] if research_output else '无输出'}

## 请判断
输出 JSON 格式的评估结果（只输出 JSON，不要其他内容）：

```json
{{
  "satisfied": true/false,
  "experiment_success": true/false,
  "supports_paper": true/false,
  "reason": "判断理由",
  "next_action": "proceed_to_writing" | "retry_experiment" | "mark_failed"
}}
```
""", timeout=600)

            # 解析 Planner 评估结果
            satisfied = False
            try:
                # 尝试从输出中提取 JSON
                json_match = re.search(r'\{[^{}]*"satisfied"[^{}]*\}', eval_output, re.DOTALL)
                if json_match:
                    eval_json = json.loads(json_match.group())
                    satisfied = eval_json.get("satisfied", False)
                    reason = eval_json.get("reason", "")
                    self.log(f"  Planner 判断: satisfied={satisfied}, reason={reason[:100]}", "INNERLOOP")
                else:
                    # 简单的关键词判断
                    satisfied = '"satisfied": true' in eval_output.lower() or '"satisfied":true' in eval_output.lower()
            except json.JSONDecodeError:
                satisfied = "satisfied.*true" in eval_output.lower() or "实验成功" in eval_output

            if satisfied:
                issue["status"] = "completed"
                self._save_action_plan(action_plan)
                self.log(f"  Issue {issue.get('id')} 完成!", "INNERLOOP")

                # 实验完成后：生成图表并更新论文
                self._generate_figures_from_results()
                return

            self.log(f"  Inner Loop #{loop_num} 未通过，继续迭代...", "INNERLOOP")

        # 超过最大迭代次数
        issue["status"] = "failed"
        issue["failure_reason"] = f"超过最大迭代次数 {max_loops}"
        self._save_action_plan(action_plan)
        self.log(f"警告: {issue.get('id')} 超过最大迭代次数 {max_loops}，标记为 failed", "WARN")

    def _run_writing_phase(self, action_plan: dict):
        """执行写作阶段

        将所有 WRITING_ONLY 任务和已完成实验的写作任务交给 Writer 处理。

        Args:
            action_plan: action plan 字典
        """
        issues = action_plan.get("issues", [])

        # 收集所有写作任务
        writing_tasks = []

        for issue in issues:
            if issue.get("type") == "WRITING_ONLY":
                writing_tasks.append({
                    "id": issue.get("id"),
                    "title": issue.get("title"),
                    "description": issue.get("description", ""),
                    "actions": issue.get("actions", []),
                })
                issue["status"] = "in_progress"
            elif issue.get("type") == "EXPERIMENT_REQUIRED" and issue.get("status") == "completed":
                # 实验完成后的写作任务
                for action in issue.get("actions", []):
                    if action.get("agent") == "writer":
                        writing_tasks.append({
                            "id": issue.get("id"),
                            "title": f"整合 {issue.get('title')} 实验结果",
                            "description": action.get("task", ""),
                            "actions": [action],
                        })

        if not writing_tasks:
            self.log("没有写作任务需要执行", "WRITER")
            return

        # 构建写作任务描述
        task_list = []
        for i, task in enumerate(writing_tasks, 1):
            task_list.append(f"""
### 任务 {i}: {task['id']} - {task['title']}
{task['description']}
""")

        self.log(f">>> Writer 处理 {len(writing_tasks)} 个写作任务", "WRITER")

        self.run_agent("writer", f"""
请根据以下审稿修改任务，更新论文 Latex/main.tex。

## 修改任务列表

{''.join(task_list)}

## 注意事项
1. 按优先级处理：Major Issues > Minor Issues
2. 每个修改后确保 LaTeX 语法正确
3. 如果有新实验结果，整合到论文中
4. 同步更新 report.md
5. 保持论文核心贡献不变
6. 参考 paper_example/ 目录的高质量论文风格

## 参考文件
- auto_research/state/latest_review.md - 审稿报告
- auto_research/state/findings.yaml - 研究发现
- auto_research/state/action_plan.yaml - 完整任务列表
""", timeout=3600)

        # 标记写作任务完成
        for issue in issues:
            if issue.get("type") == "WRITING_ONLY":
                issue["status"] = "completed"

        self._save_action_plan(action_plan)
        self.log("写作阶段完成", "WRITER")

    def run_paper_iteration(self) -> bool:
        """执行论文审稿迭代，返回是否应该继续"""
        self.iteration += 1
        paper_state = self.load_paper_state()
        paper_requirements = self.load_paper_requirements()
        current_score = paper_state.get("current_score", 0)

        self.log(f"\n{'='*60}")
        self.log(f"Paper Review Iteration {self.iteration}")
        self.log(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log(f"当前评分: {current_score}/10 | 目标: {PAPER_ACCEPT_THRESHOLD}/10")
        self.log(f"{'='*60}\n")

        # 0. 首次迭代：生成图表并设置基本结构
        if self.iteration == 1:
            self.log("First iteration: generating figures and initializing paper...")
            self.generate_figures()

            # 让 writer 完成初始设置（作者信息、图表引用等）
            req_summary = yaml.dump(paper_requirements, allow_unicode=True) if paper_requirements else "无特殊需求"
            self.run_agent(
                "writer",
                f"""这是论文审稿的第一次迭代。请完成以下初始化工作：

1. 更新 Latex/main.tex 中的作者信息（根据 paper_requirements.yaml）
2. 确保所有生成的图表（Latex/figures/fig*.pdf）都正确引用到论文中
3. 检查论文结构是否完整
4. 确保符合 EuroMLSys SIGPLAN 双栏六页格式

论文需求配置：
```yaml
{req_summary}
```

参考 paper_example/ 目录中的高质量论文。""",
                timeout=3600,
            )

        # 1. 编译当前版本的 LaTeX
        if not self.compile_latex():
            self.log("LaTeX compilation failed, asking writer to fix...")
            self.run_agent("writer", "LaTeX 编译失败，请修复语法错误并确保能正确编译")
            if not self.compile_latex():
                self.log("Still cannot compile, skipping this iteration...")
                return True

        # 2. 转换 PDF 为图像用于视觉审核
        page_images = self.pdf_to_images()
        visual_review_section = ""
        if page_images:
            visual_review_section = f"""

## 视觉审核

请使用 Read 工具读取以下论文页面图像，进行视觉效果审核：
{chr(10).join(f'- {img}' for img in page_images)}

重点检查：
- 图表大小是否合适，字体是否清晰可读
- 排版是否专业（对齐、间距、边距）
- 信息密度是否适中
- 整体视觉效果是否达到 research publication 水平
"""

        # 3. Reviewer Agent 审稿
        self.log("Running reviewer agent...", "INFO")
        review_output = self.run_agent(
            "reviewer",
            f"""请审阅当前论文 Latex/main.tex 和生成的 Latex/main.pdf。

根据 EuroMLSys 标准进行评审：
- 技术质量 (40%)
- 论文呈现 (30%)
- 创新性 (20%)
- 写作质量 (10%)
{visual_review_section}
输出详细的审稿报告，包括：
1. 总体评分 (X/10)
2. 各项评分
3. Major Issues（必须修改）
4. Minor Issues（建议修改）
5. 具体改进建议

将审稿报告保存到 auto_research/state/latest_review.md""",
            timeout=2400,  # 40 分钟
        )

        # 3. 解析评分
        score = self.parse_review_score(review_output)
        self.log(f"Review score: {score}/10")

        # 4. 更新论文状态
        paper_state["reviews"].append({
            "iteration": self.iteration,
            "timestamp": datetime.now().isoformat(),
            "score": score,
            "log": str(self.log_file),
        })
        paper_state["current_score"] = score

        # 5. 检查是否达标
        if score >= PAPER_ACCEPT_THRESHOLD:
            self.log(f"Paper accepted! Score {score}/10 >= threshold {PAPER_ACCEPT_THRESHOLD}/10")
            paper_state["status"] = "accepted"
            self.save_paper_state(paper_state)
            self._last_score = score
            self.git_commit(f"ACCEPTED: Final score {score}/10")
            self.send_notification(
                "Paper Accepted",
                f"Paper achieved score {score}/10, meeting the threshold of {PAPER_ACCEPT_THRESHOLD}/10!"
            )
            return False

        # 6. Planner 驱动的智能迭代循环
        # - Planner 分析 review，生成 action plan
        # - 执行所有实验类任务（inner loop: experimenter ↔ researcher）
        # - 执行所有写作类任务（writer）
        self.log(">>> 启动 Planner 驱动的迭代循环...", "INFO")
        planner_success = self.run_planner_cycle(review_output)

        if not planner_success:
            # Planner 循环失败，回退到简单的 Writer 修改
            self.log("Planner 循环未完成，使用简化流程...", "WARN")
            req_str = ""
            if paper_requirements:
                quality_reqs = paper_requirements.get("quality_requirements", [])
                if quality_reqs:
                    req_str = "\n\n关键质量要求：\n" + "\n".join(f"- {r}" for r in quality_reqs)

            self.run_agent(
                "writer",
                f"""请阅读最新的审稿报告 auto_research/state/latest_review.md，
根据审稿意见改进论文：

1. 首先处理所有 Major Issues
2. 然后处理 Minor Issues
3. 改进图表质量和信息密度
4. 确保符合 EuroMLSys 双栏六页格式

注意：
- 保持论文的核心贡献不变
- 每次改进后确保 LaTeX 能编译通过
- 更新 report.md 保持同步{req_str}""",
                timeout=3600,
            )

        # 7. 验证改进
        self.run_agent("validator", "验证论文改进是否符合审稿要求")

        self.save_paper_state(paper_state)
        self._last_score = score  # 保存评分用于 git commit

        # 8. 迭代总结
        self.log(f"\n{'='*40}", "INFO")
        self.log(f"迭代 {self.iteration} 总结", "INFO")
        self.log(f"{'='*40}", "INFO")
        self.log(f"  当前评分: {score}/10 (目标: {PAPER_ACCEPT_THRESHOLD}/10)", "INFO")
        self.log(f"  Token 消耗: in={self.total_input_tokens:,}, out={self.total_output_tokens:,}", "INFO")
        self.log(f"  状态: {'继续改进' if score < PAPER_ACCEPT_THRESHOLD else '已达标'}", "INFO")
        self.log(f"{'='*40}\n", "INFO")

        # 9. 清理工作区
        self.cleanup_workspace()

        # 10. Git Commit（每轮迭代都提交）
        self.git_commit(f"Iteration {self.iteration}: score {score}/10")

        # 保存检查点
        self.save_checkpoint()

        return True

    def run_iteration(self) -> bool:
        """执行一次迭代，返回是否应该继续"""
        self.iteration += 1
        self.log(f"\n{'='*60}")
        self.log(f"Iteration {self.iteration} started at {datetime.now()}")
        self.log(f"{'='*60}\n")

        # 1. 加载状态
        state = self.load_state()
        phase = self.get_current_phase(state)
        self.log(f"Current phase: {phase}")

        if phase == "completed":
            self.log("All phases completed!")
            self.send_notification("Research Completed", "All research phases have been completed!")
            return False

        # 2. 根据阶段执行不同的 Agent 流程
        if phase == "C1_quantify":
            # C1: 补充量化实验
            self.run_agent("experimenter", "检查 C1 阶段是否需要更多实验，如果需要，设计并提交")
            self.wait_for_slurm()
            self.run_agent("researcher", "分析 C1 实验结果，判断是否足够量化维度坍塌现象")

        elif phase == "C2_probe":
            # C2: 原因探究（重点）
            sub_task = self._get_c2_subtask(state)
            self.log(f"C2 sub-task: {sub_task}")

            self.run_agent("experimenter", f"针对 C2 的 {sub_task}，设计并提交实验")
            self.wait_for_slurm()
            self.run_agent("researcher", f"分析 {sub_task} 的实验结果，验证或推翻假设")

        elif phase == "C3_formulate":
            # C3: 形式化问题
            self.run_agent("researcher", "基于 C2 发现，形式化 Shape Contract 定义")

        elif phase == "C4_solver":
            # C4: 实现解决方案
            self.run_agent("experimenter", "实现 dimension repair 算法并验证")

        elif phase == "C5_validation":
            # C5: 端到端验证
            self.run_agent("experimenter", "设计并运行端到端 LLM 推理对比实验")
            self.wait_for_slurm()
            self.run_agent("researcher", "分析端到端验证结果")

        # 3. 更新报告和论文
        self.run_agent("writer", "根据最新发现更新 report.md 和 Latex")

        # 4. 验证完成度
        validation_output = self.run_agent("validator", "检查当前研究完成度")

        # 5. 检查是否阶段完成，发送通知
        new_state = self.load_state()
        new_phase = self.get_current_phase(new_state)
        if new_phase != phase:
            self.send_notification(
                f"Phase {phase} Completed",
                f"Phase {phase} has been completed. Moving to {new_phase}."
            )

        # 6. 更新迭代记录
        new_state["current_iteration"]["number"] = self.iteration
        new_state["history"].append({
            "iteration": self.iteration,
            "timestamp": datetime.now().isoformat(),
            "phase": phase,
            "log": str(self.log_file),
        })
        self.save_state(new_state)

        self.log(f"Iteration {self.iteration} completed\n")

        # 休息一段时间（避免 API 限流和额度消耗过快）
        self.log("Waiting 5 minutes before next iteration...")
        time.sleep(300)  # 5 分钟间隔，降低 API 调用频率

        return True

    def _get_c2_subtask(self, state: dict) -> str:
        """获取 C2 阶段当前应该做的子任务"""
        c2 = state.get("phases", {}).get("C2_probe", {})
        sub_tasks = c2.get("sub_tasks", [])

        for task in sub_tasks:
            if task.get("status") in ["pending", "partial"]:
                return task.get("name", "unknown")

        return "all sub-tasks completed"

    def run(self):
        """主循环"""
        self.log("="*60)
        self.log(f"GAC Automated System Started - Mode: {self.mode.upper()}")
        self.log(f"Max end time: {self.max_end_time}")
        self.log(f"Max iterations: {self.max_iterations}")
        self.log(f"Log file: {self.log_file}")
        self.log("="*60 + "\n")

        self.send_notification(
            f"{self.mode.capitalize()} Mode Started",
            f"Automated {self.mode} system started.\nMax iterations: {self.max_iterations}\nLog: {self.log_file}"
        )

        try:
            while (
                datetime.now() < self.max_end_time
                and self.iteration < self.max_iterations
            ):
                if self.mode == "paper":
                    should_continue = self.run_paper_iteration()
                else:
                    should_continue = self.run_iteration()

                if not should_continue:
                    break

        except KeyboardInterrupt:
            self.log("\nInterrupted by user")
        except Exception as e:
            self.log(f"\nError: {e}")
            self.send_notification("Error", f"{self.mode.capitalize()} system encountered an error: {e}")
            raise

        self.log("\n" + "="*60)
        self.log(f"GAC Automated System Finished - Mode: {self.mode.upper()}")
        self.log(f"Total iterations: {self.iteration}")
        if self.mode == "paper":
            paper_state = self.load_paper_state()
            self.log(f"Final paper score: {paper_state.get('current_score', 0)}/10")
            self.log(f"Paper status: {paper_state.get('status', 'unknown')}")
        self.log("="*60)


def main():
    parser = argparse.ArgumentParser(description="GAC Automated Research Orchestrator")
    parser.add_argument("--mode", type=str, default="research", choices=["research", "paper"],
                        help="Mode: 'research' for experiments, 'paper' for review iterations")
    parser.add_argument("--max-days", type=float, default=3, help="Maximum runtime in days")
    parser.add_argument("--max-iterations", type=int, default=100, help="Maximum iterations")
    args = parser.parse_args()

    orchestrator = Orchestrator(
        max_days=args.max_days,
        max_iterations=args.max_iterations,
        mode=args.mode,
    )
    orchestrator.run()


if __name__ == "__main__":
    main()
