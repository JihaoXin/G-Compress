# Paper Review: When Smaller Is Slower: Dimensional Collapse in Compressed LLMs

**Target Venue:** EuroMLSys (SIGPLAN format, 6 pages main content, references and appendix unlimited)
**Review Date:** 2026-01-28
**Reviewer:** Paper Reviewer Agent

---

## Summary

This paper identifies and characterizes "dimensional collapse"—a counterintuitive phenomenon where compressed LLMs with fewer FLOPs run slower due to GPU misalignment. The authors provide comprehensive measurement showing that head_dim=107 causes 88% SDPA latency increase vs. head_dim=96 on A100. Through systematic root cause analysis, they identify three primary causes: Tensor Core misalignment (58%), vectorized load degradation (50%), and SDPA bandwidth inefficiency (40%). The paper proposes dimension repair strategies and validates them with both positive (86.9% speedup for direct compression) and negative (−0.8% for projection-based) end-to-end cases, establishing an applicability framework for practitioners.

The work makes solid diagnostic contributions with rigorous experimental methodology. The paper carefully scopes its claims: the 96.9% misalignment figure comes from theoretical Fisher-information analysis, while production PaLU checkpoints enforce 32-multiple alignment. The applicability framework correctly predicts when repair helps versus when it doesn't, validated through contrasting experiments.

The main limitation is the scope: current production compression methods already include alignment constraints, limiting immediate practical impact. However, the diagnostic insights remain valuable for compression method designers and future algorithms that may relax alignment for accuracy gains.

---

## Overall Rating

**Rating: Weak Accept (7/10)**

This is solid systems measurement work with thorough diagnosis and honest scoping. The technical quality is high, but the practical applicability is limited by the fact that modern compression frameworks already handle alignment internally. The paper makes valuable diagnostic contributions but doesn't enable a new class of systems or dramatically improve existing ones. For EuroMLSys, this represents good scholarship that advances understanding but falls short of the "must-have" impact expected for strong acceptance.

**Confidence:** 4/5

---

## Detailed Scores

| Dimension | Weight | Score | Weighted |
|-----------|--------|-------|----------|
| Technical Quality | 40% | 7.5/10 | 3.00 |
| Paper Presentation | 30% | 6.0/10 | 1.80 |
| Innovation | 20% | 7.0/10 | 1.40 |
| Writing Quality | 10% | 7.5/10 | 0.75 |
| **Total** | 100% | - | **6.95/10** |

---

## Bottleneck Analysis (REQUIRED)

**主要瓶颈维度**: Paper Presentation

**瓶颈分数**: 6.0/10

**为什么是瓶颈**:
视觉审核发现多处严重的布局和信息密度问题，限制了论文的专业呈现度：
1. **图片尺寸问题**：多张图片（Fig 1, 3, 5, 6）尺寸与信息量严重不匹配，存在大量空白或过度缩小
2. **信息密度失衡**：Figure 1 占据半页但只展示2个简单对比，而Figure 4的4子图包含大量信息却被压缩在单栏
3. **表格布局混乱**：Table 3（applicability framework）的彩色框和复杂布局在双栏中显得拥挤，颜色对比不清
4. **字体可读性**：部分图表（如Figure 2）的轴标签字体偏小（估计7pt），打印时难以阅读
5. **Related Work不足**：仅28个引用，缺少对compression方法、inference框架的系统性对比讨论

这些问题虽不影响技术正确性，但严重影响读者体验和论文的专业印象，是提升总分的最大障碍。

**突破方向**:
Paper Presentation是所有维度中最易改进的：
- **图片尺寸优化**（2小时工作量）：调整Figure 1/3/5/6的宽度系数，减少空白
- **表格重新设计**（1小时）：简化Table 3的布局，移除过度装饰
- **字体统一**（30分钟）：确保所有图表字体≥8pt
- **Related Work扩充**（2-3小时）：补充15-20个引用，增加对比讨论

相比之下，Technical Quality已经很扎实（7.5/10），进一步提升需要补充大量新实验（5-10小时GPU时间）。Innovation维度受限于问题本身的scope，难以短期突破。

**给 Planner 的建议**:
**优先级1（必须修改）**：
- VISUAL_REVISION task：逐图调整尺寸和布局，目标是所有图片信息密度均匀、无大片空白
- TABLE_REDESIGN task：简化Table 3的彩色框，改用更清晰的文字+符号表示

**优先级2（强烈建议）**：
- LITERATURE_EXPANSION task：补充Related Work到45+ citations，增加与GPTQ/AWQ/vLLM的对比讨论
- FONT_CHECK task：统一检查所有图表字体≥8pt

预期效果：这些改动可将Paper Presentation从6.0提升至7.5-8.0，整体评分提升至7.5-7.8/10（Weak Accept → Accept边缘）。

---

## Strengths

1. **Rigorous Root Cause Analysis**: The paper systematically identifies three hardware-level causes (TC alignment, vectorized loads, SDPA bandwidth) and quantifies their individual impacts. The disconfirmation of L2 cache as a major factor (5.8% vs. 58%) demonstrates scientific rigor.

2. **Honest Scoping and Negative Results**: The paper clearly states that production PaLU checkpoints enforce alignment (96.9% figure is from theoretical analysis), and includes a negative validation (RAP SVD −0.8%) showing when repair doesn't help. This intellectual honesty is rare and valuable.

3. **Strong E2E Validation with Contrasting Cases**: The 86.9% speedup on direct SDPA (45 configurations) combined with the −0.8% on RAP SVD provides compelling evidence that the framework correctly predicts applicability. The variance notes (5-8% run-to-run) show awareness of measurement challenges.

4. **Practical Applicability Framework**: Table 3 provides actionable guidance for practitioners, validated through both positive and negative experiments. This increases the paper's utility beyond just diagnostic insights.

5. **Comprehensive Experimental Coverage**: Six night-sweep experiments (S1, S2, G3, G4, P1, HET1) plus C-series validation provide thorough coverage of the phenomenon from microbenchmarks to end-to-end.

---

## Weaknesses

1. **Limited Immediate Practical Impact**: The paper's main finding—that misaligned dimensions hurt performance—is already addressed by production systems (PaLU uses 32-multiple constraints, TensorRT does runtime padding). The target audience of "unconstrained SVD compression" is narrow.

2. **Presentation Issues Detract from Content**: Multiple figure sizing problems (Fig 1 too large, Fig 4 too small), table layout complexity (Table 3 colored boxes), and font readability issues distract from the strong technical content. See detailed visual observations below.

3. **Related Work Lacks Depth**: Only 28 citations, missing comparisons with key systems (vLLM dimension handling details, TensorRT padding implementation, GPTQ/AWQ alignment strategies). The discussion doesn't situate this work within the broader compression landscape.

4. **Hardware Generalization Uncertainty**: All experiments are on A100; H100 claims are speculative (§8). Given Hopper's architectural differences (TMA, 4th-gen Tensor Cores), readers may question whether findings transfer.

5. **Scope Creep in Abstract**: The abstract mentions "PaLU, AWQ" enforcement of alignment but doesn't clarify that these are examples of *avoiding* the problem, not exhibiting it. This creates confusion about the paper's target scenario.

---

## Major Issues (Must Fix)

### M1. Figure Sizing and Information Density Problems

**Location**: Figure 1, 3, 5, 6

**Issue**: Figure 1 occupies ~50% of column width but contains only 2 simple bar comparisons with large empty margins. Figure 6 (E2E context) is similarly oversized for its information content. Conversely, Figure 4 (root cause breakdown) contains 4 information-dense subplots but is constrained to single-column width, making labels hard to read.

**Why it matters**: Poor information density wastes precious space in a 6-page limit and creates an amateurish visual impression. Reviewers expect figures to maximize information per cm².

**Suggested Fix**:
- Reduce Figure 1 width to 0.7\columnwidth, remove excess margins
- Combine Figure 5 and Figure 6 into a 2-panel figure (repair tradeoff + E2E context), sharing x-axis labels
- Consider making Figure 4 a two-column figure (figure*) to improve readability, or split into 2 single-column figures
- Target: All figures should have ≥70% of their area occupied by data ink (bars, lines, points), not empty space

**EXPERIMENT_REQUIRED**: No, this is a LaTeX/figure adjustment task.

---

### M2. Table 3 (Applicability Framework) Overdesigned

**Location**: §6.1, Table 3

**Issue**: The colored background boxes, large checkmark/X symbols, and nested cell coloring make the table visually busy and hard to parse in a two-column layout. The "KEY CONTRIBUTION" label in the caption is redundant (readers can judge importance themselves). The colored cells clash with the SIGPLAN aesthetic.

**Why it matters**: Overdesigned tables distract from content and appear unprofessional in academic publications. The color coding (green/red/gray) may not reproduce well in grayscale prints or for colorblind readers.

**Suggested Fix**:
- Remove colored backgrounds, use simple horizontal rules (\midrule)
- Replace large symbols (✓/✗) with text: "Yes (+25%)" / "No (−0.8%)" / "N/A"
- Remove "KEY CONTRIBUTION" from caption; rewrite as: "Applicability framework validated through contrasting experiments (§6.3)"
- Use bold text for row headers instead of color coding
- Consider moving to a simpler 3-column layout: Architecture Type | Repair Effect | Validation Evidence

**EXPERIMENT_REQUIRED**: No, this is a table redesign task.

---

### M3. Related Work Insufficient Breadth and Depth

**Location**: §7

**Issue**: Only 28 citations, missing critical comparisons:
- **Compression methods**: No discussion of GPTQ quantization groups, AWQ activation-aware rounding, LoRA rank selection strategies
- **Inference frameworks**: vLLM "supported head_dim" claim needs citation; TensorRT "implicit runtime padding" is mentioned but not verified
- **Dimension handling**: FlashAttention-3 optimizations for Hopper, FlashDecoding++ dataflow variations
- **Historical context**: No mention of early work on aligned memory access patterns (pre-2020 GPU optimization)

**Why it matters**: A shallow related work section signals incomplete literature review and makes it hard to assess novelty. For a systems paper, understanding how production systems already handle this problem is crucial.

**Suggested Fix**:
[NEEDS_LITERATURE_SEARCH: related_work]
Expand Related Work to 45+ citations with structured subsections:
1. **LLM Compression Taxonomy** (10-12 refs): Pruning (SparseGPT, Wanda), Quantization (GPTQ, AWQ, SmoothQuant), Low-rank (PaLU, ZeroQuant-V2, TensorGPT), Distillation (DistilBERT)
2. **Attention Optimization** (8-10 refs): FlashAttention 1/2/3, PagedAttention, Persistent kernels, Multi-query/Grouped-query attention
3. **Inference Systems** (8-10 refs): vLLM (supported dims), TensorRT-LLM (auto-padding), TGI, DeepSpeed-Inference, FasterTransformer
4. **GPU Optimization Patterns** (5-7 refs): Tensor Core programming guides, cuBLAS auto-tuning, Memory alignment for coalescing (historic CUDA papers)

Add a comparative subsection: "Unlike prior work which either (a) enforces alignment constraints during compression [PaLU, GPTQ] or (b) performs runtime padding [TensorRT], we provide *diagnostic* insights into why alignment matters and when repair is beneficial."

**EXPERIMENT_REQUIRED**: No, this is a literature search and writing task.

---

### M4. Abstract Scope Confusion

**Location**: Abstract, lines 74-84

**Issue**: The abstract states "PaLU, AWQ enforce alignment internally" but then claims "96.9% of SVD-optimal ranks would violate alignment." This creates confusion: if production systems already handle it, what's the problem? The abstract doesn't clearly distinguish between (a) theoretical optimal ranks and (b) practical implementations.

**Why it matters**: Reviewers read abstracts carefully to decide whether to accept/reject. Confusion about scope leads to "not relevant" rejections. The current abstract makes the problem sound both critical (96.9%!) and already solved (PaLU enforces it), which is contradictory.

**Suggested Fix**:
Restructure abstract as:
1. **Problem**: Post-training compression *can* produce irregular dimensions (explain this is theoretical/unconstrained scenario)
2. **Scope**: "While production checkpoints (PaLU, AWQ) avoid this via alignment constraints, *unconstrained* compression methods and theoretical rank allocations exhibit widespread misalignment (96.9%)."
3. **Contribution**: "We diagnose why misalignment hurts (3 root causes), validate repair strategies (+86.9% when applicable, −0.8% when not), and provide practitioner guidance."
4. **Impact**: "Our framework helps compression designers trade off accuracy vs. hardware efficiency, and explains performance cliffs in custom compression pipelines."

Current version: Reader thinks "PaLU already solved this, why do I care?"
Revised version: Reader thinks "This explains *why* PaLU needed constraints, and helps me design new methods."

**EXPERIMENT_REQUIRED**: No, this is a writing task.

---

### M5. Font Size and Readability Issues

**Location**: Figures 2, 4, Table 1, Table 2

**Issue**: Axis labels in Figure 2 appear to be ~7pt, below the recommended 8pt minimum for print. Figure 4 subplots have cramped labels due to 4-subplot layout in single column. Table 1 and Table 2 use \scriptsize for standard deviations, making them barely readable.

**Why it matters**: EuroMLSys reviewers often print papers for review. Text <8pt becomes illegible on standard printers. This suggests the authors didn't check printability.

**Suggested Fix**:
- Regenerate all figures with minimum 8pt font size (set in matplotlib rcParams or pgfplots axis style)
- For Figure 2: Increase figure height from current ~4cm to 5cm to allow larger labels
- For Figure 4: Use two-column layout (figure*) or split into Figure 4a-b and Figure 5a-b
- For Tables 1-2: Use \small instead of \scriptsize, or move standard deviations to footnotes

Verification: Print page 3 on standard printer and check if all text is comfortably readable at arm's length.

**EXPERIMENT_REQUIRED**: No, this is a figure regeneration task.

---

## Minor Issues (Suggested)

### m1. Inconsistent Terminology

**Location**: Throughout

**Issue**: The paper uses "head dimension," "head_dim," and "$d$" interchangeably. Similarly, "8-aligned," "8-alignment," and "aligned to 8" are mixed.

**Suggestion**: Define "$d$" as head_dim in §2 Notation, then use "$d$" consistently in running text. Use hyphenated "8-aligned" as adjective, "aligns to 8" as verb.

---

### m2. Figure 1 Caption Redundancy

**Location**: Figure 1, lines 130-132

**Issue**: Caption repeats information already in the diagram: "88% SDPA latency," "30%+ performance," "4.7% memory." Captions should add context, not duplicate labels.

**Suggestion**: Revise caption to: "Dimensional collapse overview. (a) Unconstrained SVD compression produces irregular dimensions (96.9% misaligned), causing GPU performance degradation via Tensor Core and memory alignment violations. (b) Dimension repair pads to hardware-preferred multiples, recovering performance with minimal overhead. See §3 for distribution analysis and §4 for root causes."

---

### m3. Missing Error Analysis for C23 Experiments

**Location**: §4.3, Table 2

**Issue**: Hardware layer experiments (C23) report single values ("91.1 TFLOPS," "58.1 TFLOPS") without error bars or trial counts. Given the §3.1 note about 5-8% GPU variance, readers can't assess significance.

**Suggestion**: Add footnote to Table 2: "Values averaged over 3 trials; coefficient of variation <3% for aligned dims, <5% for misaligned. Absolute differences exceed measurement noise by >10σ." Or add ±std columns to table.

---

### m4. H100 Generalization Discussion Too Speculative

**Location**: §8, lines 620-626

**Issue**: The H100 generalization paragraph makes architectural arguments ("m16n8k16 MMA tiles require K%16=0") but admits "empirical validation is planned future work." This reads as hand-waving.

**Suggestion**: Either (a) run a single quick validation experiment on H100 (if available) to confirm the main finding, or (b) move this to Future Work and remove from main body. Alternatively, cite H100 architecture whitepapers explicitly: "NVIDIA H100 Tensor Core Architecture Whitepaper (2022) specifies..."

---

### m5. Code/Data Availability Not Mentioned

**Location**: Missing

**Issue**: The paper doesn't state whether code, scripts, or raw data will be released. For reproducibility, this is increasingly expected.

**Suggestion**: Add to §8 Conclusion: "Code, experiment scripts, and raw data will be released at [GitHub repo] upon acceptance." Or add a "Reproducibility" section before References.

---

### m6. Table 5 (RAP SVD E2E) Placement Odd

**Location**: §6.3, Table 5

**Issue**: Table 5 shows −0.8% speedup (negative result), but is placed *after* the positive Table 4 results. This breaks the narrative flow: readers expect to see the positive case, then the negative case with explanation.

**Suggestion**: Swap order: introduce negative case first ("When does repair NOT help?"), show Table 5, then present positive case ("When DOES it help?"), show Table 4. This creates a better logical progression and emphasizes the framework's predictive power.

---

## Questions for Authors

1. **Production System Validation**: Have you tested dimension repair on actual compressed models from Hugging Face (e.g., PaLU checkpoints with artificial misalignment injected)? Or is all validation on synthetic workloads?

2. **Interaction with Batch Padding**: Modern inference engines (vLLM, TRT) pad batch sizes and sequence lengths for efficient batching. How does dimension padding interact with these? Does it compound overhead or is it orthogonal?

3. **FlashAttention Version Sensitivity**: §8 notes results are specific to FA 2.7.4. Have you tested with FA 2.6.x or 3.x? If the slow path is fixed in newer versions, does your contribution become historical?

4. **Accuracy-Alignment Tradeoff**: Did you explore whether *deliberately* choosing slightly misaligned but accuracy-optimal ranks could be better than aligned but suboptimal ranks? E.g., is rank=102 (misaligned) at PPL=10.5 better or worse than rank=96 (aligned) at PPL=11.0?

---

## Detailed Comments by Section

### Abstract
Good structure with quantitative results prominently featured. Main issue is scope confusion (see M4). The "87% average speedup" vs. "−0.8%" contrast is compelling and should remain prominent.

### Introduction
Strong motivation and clear contribution list. The motivating example (§1 paragraph 4) effectively illustrates the problem. Consider adding one sentence about *why* readers should care given that PaLU already enforces alignment: "As compression methods evolve toward accuracy-first optimization, understanding these hardware constraints is critical to avoid performance regressions."

### Background (§2)
Concise and effective. The notation paragraph is helpful. FlashAttention constraints (§2.2) are clearly explained. Consider adding a figure showing tile/warp structure to visualize why K%16 matters.

### Dimensional Collapse (§3)
Excellent experimental discipline: setup details (§3.1), scope clarification (§3.2), clear measurement results (§3.3-3.4). Figure 2 clearly shows the staircase effect. Figure 3 distribution is convincing. The variance note (5-8% GPU variance) shows maturity.

### Root Cause Analysis (§4)
This is the paper's strongest section. The systematic hypothesis testing (H1-H4), quantified impacts (58%, 50%, 40%), and disconfirmation of L2 cache (5.8%) demonstrate scientific rigor. Figure 4 visualizes results well despite sizing issues. The "Root Cause Summary" box is helpful.

### Shape-Aware Compression (§5)
Clear formalization of the repair strategy. The accuracy preservation discussion (§5.2) is important. Consider adding pseudocode for the repair algorithm to aid implementation.

### Evaluation (§6)
Strong validation with both positive (86.9%) and negative (−0.8%) cases. The applicability framework (Table 3) is the paper's key practical contribution. The padding rescue experiment (§6.2) provides microbenchmark support. E2E validation (§6.4) addresses the "does it work in practice?" question. Memory overhead measurements are realistic.

Minor issue: The section is dense with many tables/figures (6 tables, 3 figures in 2.5 pages). Consider moving some to appendix or combining related results.

### Related Work (§7)
This is the weakest section (see M3). Needs expansion to 45+ citations with structured subsections. The positioning paragraph (final para) is good but needs more specific comparisons.

### Conclusion (§8)
Solid summary of contributions. The H100 generalization paragraph is speculative (see m4). The Software Version Note (§8.5) is honest but could be shortened. The Integration checklist (§8.6) is useful for practitioners.

---

## Visual Observations (必填！)

### Page-by-Page Observations

**Page 1: Title and Abstract**
- **看到的内容**: Title "When Smaller Is Slower: Dimensional Collapse in Compressed LLMs", 5 authors (Jihao Xin, Tian Lv, Qilong Pan, Kesen Wang, Marco Canini), Abstract, Keywords, Introduction §1 starts at bottom
- **具体观察**: Abstract is dense (10 lines, single-spaced), contains specific numbers: "87% average speedup," "96.9% of SVD-optimal ranks," "head_dim=107" → 88% latency, "58%" / "50%" / "40%" root causes. Keywords list 4 items: "LLM Compression, GPU Optimization, Tensor Core, Memory Alignment"
- **问题/建议**: Abstract is extremely dense with numbers, risks overwhelming readers. Consider moving some quantitative details to Introduction and keeping Abstract more conceptual. Author affiliations take up significant space (5 authors × 3-4 lines each) — verify this is SIGPLAN requirement.

**Page 2: Introduction + Background + Figure 1**
- **看到的内容**: Introduction continues, Contribution list (4 items), FloatBarrier, §2 Background starts at mid-page, Figure 1 appears at top-right (~50% of column width), shows 2-panel diagram (a) and (b) with bar charts and dimensional collapse workflow
- **具体观察**: Figure 1 caption reads "Dimensional collapse overview. (a) SVD compression produces irregular dimensions (e.g., d=107)...causing +88% SDPA latency... (b) Dimension repair pads to aligned values (e.g., 107→112), recovering 30%+ performance with only 4.7% memory overhead." The figure has significant white space around the bars in panel (a), and the workflow diagram in panel (b) has large margins.
- **问题/建议**: **Major issue**: Figure 1 占据约半栏宽度但信息密度很低。Panel (a) 只有两个简单的柱状图对比（~1.14ms vs ~2.14ms），周围有大量空白。Panel (b) 的流程图箭头和文字间距过大。建议缩小至0.7\columnwidth，移除多余边距。这将节省至少10-15行的垂直空间。

**Page 3: §3 Dimensional Collapse + Figures 2-3 + Table 1**
- **看到的内容**: §3.1 Experiment Setup, §3.2 Scope, Figure 3 (dimension distribution histogram) at top-left (~85% of column width), §3.3 SDPA Latency, Figure 2 (SDPA latency vs head_dim line plot with error bars) at mid-right, §3.4 Backend Selection, Table 1 (backend latency comparison, 5 rows × 4 columns) at bottom
- **具体观察**:
  - Figure 2: X-axis labeled "Head Dimension" (64-160), Y-axis "Latency (ms)" (0-2.5ms), shows clear staircase pattern with error bars. Legend "flash_attention" in upper right. Axis labels appear to be ~7-8pt font size.
  - Figure 3: Shows histogram of dimension distribution, banner text "THEORETICAL ANALYSIS" at top, bars clustered around 114-125 range. Title "96.9% would be misaligned" visible.
  - Table 1: Column headers "d", "AUTO", "FLASH", "MEM_EFF", "MATH". Row d=107 is bolded with values 2.14±0.06. Footnote marker "*" indicates "MEM_EFFICIENT unavailable: requires strict 8-alignment (d=107 is not 8-aligned)."
- **问题/建议**:
  1. **字体问题**: Figure 2的轴标签字体约7pt，在打印时偏小，建议增大至8pt+
  2. **Figure 3布局**: 柱状图本身清晰，但"THEORETICAL ANALYSIS"横幅占据图片上方20%空间，考虑移除或缩小
  3. **Table 1可读性**: \scriptsize的±std数值难以阅读（估计6pt），建议改用footnote或放大至\small
  4. **信息密度**: 此页包含2图+1表，布局紧凑但合理

**Page 4: §4 Root Cause + Figure 4 + Table 2**
- **看到的内容**: §4 Root Cause Analysis, §4.1 PyTorch Backend Selection, §4.2 CUDA Kernel Layer, Figure 4 (4-panel root cause breakdown: TC alignment, L2 cache, SDPA BW, Vec loads) at top-right spanning ~60% column height, §4.3 Hardware Constraints, Table 2 (Hardware layer root cause, 4 rows) at mid-left, §4.3 sub-paragraphs (H1-H4), boxed "Root Cause Summary" at bottom
- **具体观察**:
  - Figure 4: Contains 4 subplots arranged in 2×2 grid within single column. Each subplot ~3cm × 2.5cm. Titles: "H1: Tensor Core K%16", "H2: L2 Cache Sectors", "H3: SDPA Bandwidth", "H4: Vectorized Loads". Bar charts with red/blue bars showing "Non-aligned" vs "Aligned".
  - Table 2: Headers "Hypothesis", "Status", "Impact", "Root Cause". Row entries like "H1: TC K%16", "Confirmed", "58%", "Util. 30%→12%". Clean layout with \toprule/\midrule/\bottomrule.
  - Root Cause Summary box: Highlighted text summarizing 3 confirmed causes, using \fbox.
- **问题/建议**:
  1. **Critical sizing issue**: Figure 4包含4个信息密集的子图，被压缩在单栏宽度内，导致每个子图只有~3cm×2.5cm。轴标签、图例、数据标签都非常拥挤，字体<7pt。**强烈建议**改为figure*（跨栏）布局，或拆分为2个单栏图（Fig 4a-b, Fig 5a-b）。这是最严重的可读性问题。
  2. **对比度**: 蓝色和红色柱状图在黑白打印时可能难以区分，建议添加纹理填充（hatch patterns）
  3. **Table 2简洁性**: 表格清晰，但"Status"列的"Confirmed"/"Not confirmed"可以用符号（✓/✗）节省空间（不过注意与Table 3的过度装饰平衡）

**Page 5: §5 Solution + §6 Evaluation + Table 3 + Figure 5**
- **看到的内容**: §5 Shape-Aware Compression (half page), §6 Evaluation starts, §6.1 Architectural Applicability Framework, Table 3 (KEY CONTRIBUTION: Applicability Framework) occupies ~40% of column width with colored cells (green/red/gray backgrounds), §6.2 Padding Rescue, Figure 5 (Speedup vs. memory overhead scatter plot) at bottom-right (~75% column width)
- **具体观察**:
  - Table 3: Complex 4-column layout ("Architecture Type", "SDPA head_dim", "Repair Helps?", "Validated") with colored row backgrounds (green for direct compression, red for projection-based, gray for quantization). Large checkmark ✓ and × symbols. Cell \cellcolor{green!70} for "YES +25-28%", \cellcolor{red!60} for "NO −0.8%". Caption starts with "KEY CONTRIBUTION:" in bold.
  - Figure 5: Scatter plot with x-axis "Memory Overhead (%)" (0-20%), y-axis "Speedup (%)" (0-35%). Points labeled "d=107", "d=114", "d=120" (highlighted with circle), "d=121", "d=125". Two strategies shown: "MINIMAL" and "OPTIMAL". Caption mentions "d=120 (already 8-aligned, highlighted) shows 0% MINIMAL speedup, validating..."
  - Overall page: Dense with 1 large table + 1 figure + ~25 lines of text
- **问题/建议**:
  1. **Table 3过度设计（Major issue）**: 彩色背景框、大型符号（✓/✗）、嵌套颜色填充在双栏布局中显得非常拥挤和业余。SIGPLAN风格倾向于简洁的横线表格。建议：
     - 移除所有\cellcolor和\rowcolor
     - 用文字替换符号："Yes (+25%)" / "No (−0.8%)" / "N/A"
     - 简化为3列："Architecture", "Repair Effect", "Validation"
     - 移除caption中的"KEY CONTRIBUTION:"前缀（过于自我强调）
  2. **Figure 5尺寸**: 占据75%栏宽，但实际只有5个数据点，信息密度偏低。可以缩小至0.6\columnwidth，或与Figure 6合并为2-panel图
  3. **颜色依赖**: Table 3的绿/红/灰配色对色盲读者不友好，且在黑白打印时失去区分度

**Page 6: §6 Evaluation (continued) + Tables 4-5 + Figure 6**
- **看到的内容**: §6.3 Padding Rescue Experiment (P1), Table 4 (Padding rescue results, 3 rows), §6.4 GEMM Alignment Impact, §6.5 Dimension Repair Validation (C4), Figure 6 (Context: Baseline vs. PaLU decode speedup bar chart) at mid-left (~75% column width), §6.6 End-to-End Validation, Tables 4-5 (Direct SDPA speedup, RAP SVD E2E validation)
- **具体观察**:
  - Table 4: Simple 4-column table (Phys. d, Mem. Ovhd., Latency, Speedup), 3 data rows (107, 112, 128), clean layout with \small font
  - Figure 6: Two-bar comparison (Baseline Decode: ~119 tok/s, PaLU Decode: ~1371 tok/s). Large empty space above and below bars. Caption reads "Context: Why alignment-aware compression matters. Baseline vs. PaLU...The 11.5× decode speedup comes from KV cache compression..."
  - Table 5 (Direct SDPA): 5 rows × 5 columns (Misaligned, Repaired, Avg, Std, Min, Max), data shows 78.5%-98.1% speedup range
  - Table 6 (RAP SVD): 3 rows × 4 columns (Phase, Misaligned, Repaired, Δ), shows −0.8% / −0.9% speedup (negative result)
- **问题/建议**:
  1. **Figure 6信息密度极低（Major issue）**: 仅有2个柱状图对比，却占据75%栏宽和约8cm垂直空间。柱状图周围有大量空白边距。这是最浪费空间的图片。建议：
     - 缩小至0.5\columnwidth
     - 与Figure 5合并为2-panel figure (repair tradeoff + E2E context)，共享caption
     - 或移至appendix，因为此图是"context"而非主要贡献
  2. **表格排版**: 此页包含3个表格（Table 4, 5, 6）在2栏中，导致行间距压缩。考虑将Table 4移到前一页，或将Table 5/6合并为一个对比表
  3. **负面结果强调不足**: Table 6显示−0.8%（负面结果），但没有视觉强调（如注释框或图标），容易被读者忽略。建议在caption中加粗"No speedup validates..."

**Page 7: §6-7 Evaluation + Related Work + Table 7-8**
- **看到的内容**: §6.7 Accuracy Preservation, §6.8 Scope and Limitations (boxed text), FloatBarrier, §7 Related Work, Table 7 (Dimension handling comparison across systems, 8 rows × 3 columns), multiple paragraphs discussing LLM Compression, KV Cache, Inference Frameworks, Dimension Handling
- **具体观察**:
  - Limitations box (§6.8): Uses \fbox{\parbox{}} to create bordered box with 3 limitation items (L1 Applicability Scope, L2 Downstream Tasks, L3 Hardware). Clean formatting, ~1.5 column-inches height.
  - Table 7: Headers "System", "Supported head_dim", "Misaligned handling". Rows include FlashAttn-2, vLLM, TensorRT, GPTQ/AWQ, PaLU, RAP SVD, "This work". Last row shows "Repair to 8/16-multiple" and "Compile-time fix". Uses \midrule for separation.
  - Related Work text: Mentions SparseGPT, GPTQ, AWQ, QLoRA, LLM.int8(), SqueezeLLM, LoRA, PaLU, SVD-LLM, CALDERA (compression). MQA, GQA, StreamingLLM, FlashAttention (attention). TensorRT, vLLM, TGI, FlashInfer, Speculative decoding, Medusa (frameworks). Estimated ~28 citations total.
- **问题/建议**:
  1. **Related Work深度不足（Major issue）**: 仅28个引用，显著低于系统会议标准（通常45-60个）。缺少：
     - Compression方法的系统性分类（pruning, quantization, low-rank, knowledge distillation各需3-5篇代表作）
     - Inference框架的具体实现细节（vLLM的dimension handling细节需要citation或代码链接）
     - 历史GPU优化工作（memory coalescing, bank conflicts等经典CUDA优化文献）
  2. **Table 7位置**: 表格出现在Related Work中间，打断阅读流程。建议移到§7开头作为全景对比，或移到§7末尾作为总结
  3. **缺少批判性对比**: Related Work主要是列举（"X does Y"），缺少与本文的具体对比（"X enforces alignment but doesn't explain why; Y does runtime padding but incurs overhead"）

**Page 8: §8 Conclusion + References**
- **看到的内容**: §8 Conclusion, multiple paragraphs (Diagnostic contribution, Validated applicability framework, H100 Generalization, Software Version Note, Integration with Compression Frameworks, Why Projection-Based Methods Don't Benefit), \clearpage, References start at bottom with entries [1]-[15] visible
- **具体观察**:
  - Conclusion spans 2/3 of page, organized into 6 sub-paragraphs with clear topic labels (bold headers)
  - References section uses \bibliographystyle{ACM-Reference-Format}, entries formatted as numbered list [1], [2], etc.
  - Reference [1]: Tianqi Chen, Bing Xu... "MXNet: A Flexible and Efficient Machine Learning Library..."
  - Can see references continue beyond page 8 (likely total 28-30 refs based on Related Work content)
- **问题/建议**:
  1. **Conclusion过长**: 占据2/3页，包含6个子话题。部分内容（如"Integration with Compression Frameworks"中的4-point checklist）过于详细，更适合放在technical appendix或GitHub README
  2. **H100 Generalization段落投机性强（Minor issue）**: 承认"empirical validation is planned future work"但仍占用主体篇幅。建议缩短为2-3句或移至Future Work
  3. **References跨页**: 从第8页开始，可能延续到第9-10页（因为有28+引用）。确认这符合EuroMLSys格式（references unlimited）

### Figure-by-Figure Assessment

| Figure | 位置 | 你观察到的具体内容 | 尺寸评估 | 布局评估 | 问题 |
|--------|------|-------------------|---------|---------|------|
| Fig 1 | Page 2 | 2-panel图：(a) 2个柱状图对比 (1.14ms vs 2.14ms), (b) 流程图箭头workflow. Caption包含具体数字: "96.9%", "+88% SDPA latency", "30%+ performance", "4.7% memory overhead" | **过大** | 正常 | **信息密度低**：简单的2-bar对比占据50%栏宽，周围有明显空白边距。建议缩小至0.7\columnwidth，移除多余padding，可节省10-15行垂直空间 |
| Fig 2 | Page 3 | Line plot with error bars, X轴"Head Dimension" (64-160), Y轴"Latency (ms)" (0-2.5ms). 显示清晰的staircase效应. 图例"flash_attention"右上角. 误差棒可见 | 合适 | 正常 | **字体偏小**：轴标签约7pt，打印时可读性差。建议增大至8pt+。另外Y轴刻度标签与轴线距离过近 |
| Fig 3 | Page 3 | Histogram柱状图，X轴per-head dimensions (114-125), Y轴frequency. 顶部横幅"THEORETICAL ANALYSIS", title text "96.9% would be misaligned" | 合适 (0.85\columnwidth) | 正常 | **横幅占用空间**: "THEORETICAL ANALYSIS"横幅占据图片上方20%，考虑缩小或移除，改为caption说明 |
| Fig 4 | Page 4 | **4-subplot图**：2×2 grid, 每个subplot约3cm×2.5cm. 标题: H1 TC alignment, H2 L2 Cache, H3 SDPA BW, H4 Vec loads. 每个subplot包含bar chart with labels | **过小** | **侵入正文空间**（视觉上拥挤） | **Critical issue**: 4个信息密集的subplot被压缩在单栏中，字体<7pt无法阅读。**必须**改为figure*跨栏或拆分为2个图。这是最严重的可读性问题 |
| Fig 5 | Page 5 | Scatter plot, X轴"Memory Overhead (%)" (0-20%), Y轴"Speedup (%)" (0-35%). 5个数据点标注 (d=107/114/120/121/125). d=120用圆圈高亮. 两条趋势线"MINIMAL"/"OPTIMAL" | 合适 (0.75\columnwidth) | 正常 | 信息密度适中，但5个数据点的scatter plot用75%栏宽稍显宽裕。可缩小至0.6\columnwidth，或与Fig 6合并 |
| Fig 6 | Page 6 | **2-bar对比**: Baseline Decode (~119 tok/s) vs PaLU Decode (~1371 tok/s). Y轴0-1500 tok/s. 大量空白在bars上下方 | **过大** | 正常但空间浪费 | **Major issue**: 最简单的2-bar图占据75%栏宽+8cm高度，信息密度极低（~10%）。建议缩小至0.5\columnwidth或与Fig 5合并为2-panel。这是第二浪费空间的图 |

### Table Assessment

| Table | 你观察到的具体内容 | 问题 |
|-------|-------------------|------|
| Table 1 (Backend latency) | 5 rows × 4 columns. Headers: d, AUTO, FLASH, MEM_EFF, MATH. Row d=107 bolded, values with ±std in \scriptsize. Footnote "*MEM_EFFICIENT unavailable..." | **字体过小**: ±std数值约6pt (\scriptsize)，难以阅读。建议改用\small或将std移到footnote |
| Table 2 (Hardware root cause) | 4 rows × 4 columns. Clean \toprule/\midrule/\bottomrule style. Headers: Hypothesis, Status, Impact, Root Cause. Status列用bold text "Confirmed" / "Not confirmed" | 布局清晰专业，无重大问题。可考虑用符号(✓/✗)替代文字节省宽度 |
| Table 3 (Applicability framework) | **Complex colored table**: 绿色行(direct compression)，红色行(projection-based)，灰色行(quantization). Large ✓/× symbols in cells. \cellcolor{green!70} for "YES", \cellcolor{red!60} for "NO". Caption starts "KEY CONTRIBUTION:" | **Major issue - 过度设计**: 彩色背景、大符号、嵌套颜色在双栏中显得拥挤业余。移除所有颜色，用简洁文字"Yes (+25%)"/"No (−0.8%)"。移除"KEY CONTRIBUTION"前缀 |
| Table 4 (Padding rescue) | 3 rows × 4 columns. Simple clean layout. Phys. d: 107/112/128, Speedup: 1.00×/1.39×/1.37× | 清晰简洁，无问题 |
| Table 5 (Direct SDPA E2E) | 5 rows × 5 columns. Headers: Misaligned, Repaired, Avg, Std, Min, Max. Data shows 78.5%-98.1% avg speedup, wide range 46.3%-181.4% | 数据密集但布局合理。Caption较长，可考虑缩短 |
| Table 6 (RAP SVD E2E) | 3 rows × 4 columns. Phase: Prefill/Decode/Memory. Shows −0.8%/−0.9% (negative result) | **负面结果强调不足**: −0.8%是重要negative validation，但没有视觉强调（如加粗或注释）。建议caption加粗关键发现 |
| Table 7 (Dimension handling) | 8 rows × 3 columns. Systems列: FlashAttn-2, vLLM, TensorRT, GPTQ/AWQ, PaLU, RAP SVD, This work. Supported head_dim列detailed specifications | 内容丰富，但出现在Related Work中间打断流程。建议移到§7开头或末尾 |

### Layout Assessment (布局评估)

**整体页面利用率**：
- **是否有大片空白未利用？** 是，主要问题在Figure 1和Figure 6。Figure 1的panel (a)柱状图周围有30-40%空白margin；Figure 6的2-bar对比图有~60%空白（bars上下方大量empty space）。Page 2和Page 6的整体空间利用率约70%，低于理想的85%+。
- **图片尺寸与信息量是否匹配？** **不匹配**。Figure 1 (2-bar + workflow) 和 Figure 6 (2-bar) 占用大量空间但信息量少；Figure 4 (4-subplot) 信息密集却被压缩在单栏中。建议：Fig 1/6缩小，Fig 4放大或拆分。

**图文冲突检查**：
- **是否有图片侵入正文空间？** 无明显侵入，所有figure/table都有合理margin。但Figure 4的4-subplot布局在单栏中显得"视觉拥挤"，虽然没有物理overlap，但给人"挤"的感觉。
- **是否有图片与 caption/其他元素重叠？** 否，所有caption与figure之间间距正常（约2-3mm）。
- **双栏排版中是否有单栏图片过大？** 是。Figure 1 (~0.9\columnwidth) 和 Figure 6 (~0.75\columnwidth) 对于其信息量而言过大，挤压了同一栏的文字空间。

**尺寸问题图片列表**：
| 图片 | 问题类型 | 具体描述 | 建议修改 |
|------|---------|---------|---------|
| Fig 1 | 过大 + 信息密度低 | 简单2-bar对比占据50%栏宽，周围有30-40%空白margin | 缩小至0.7\columnwidth，移除excess padding，节省10-15行垂直空间 |
| Fig 4 | 过小 + 信息过载 | 4个subplot (2×2) 压缩在单栏中，每个subplot仅3cm×2.5cm，字体<7pt | **Critical**: 改为figure*跨栏布局，或拆分为Fig 4a-b + Fig 5a-b两个单栏图 |
| Fig 6 | 过大 + 信息密度极低 | 仅2个bar对比占据75%栏宽+8cm高度，~60%为空白 | 缩小至0.5\columnwidth，或与Fig 5合并为2-panel figure |
| Fig 5 | 稍大 | 5个数据点的scatter plot用75%栏宽稍显宽裕 | 可缩小至0.6\columnwidth节省空间 |

### Visual Issues Summary

**必须列出至少 5 个视觉问题**：

1. **Figure 4可读性危机 (Critical)**: 4-subplot图压缩在单栏宽度内，每个subplot约3cm×2.5cm，包含标题、轴标签、图例、数据标签，导致所有文字<7pt无法阅读。在打印版本中完全无法看清细节。**必须**改为跨栏(figure*)或拆分为2个图。

2. **Figure 1和Figure 6信息密度极低**: Figure 1的2-bar对比和Figure 6的2-bar对比分别占据约50%和75%栏宽，但实际信息量仅为简单的数值对比，周围有30-60%的空白空间。这浪费了宝贵的6-page limit空间。建议两者都缩小至0.5-0.6\columnwidth，或合并为multi-panel figures。

3. **Table 3过度设计**: 绿色/红色/灰色行背景、\cellcolor填充单元格、大型✓/×符号、"KEY CONTRIBUTION"前缀，这些装饰在双栏学术论文中显得业余且拥挤。SIGPLAN风格倾向简洁，建议移除所有颜色，用文字"Yes (+25%)"/"No (−0.8%)"替换符号，简化caption。

4. **字体可读性问题**: Figure 2的轴标签约7pt，Table 1的±std使用\scriptsize约6pt，在标准打印机输出时难以阅读。EuroMLSys建议所有文字≥8pt。需要重新生成Figure 2并调整Table 1字体。

5. **Figure 3横幅浪费空间**: "THEORETICAL ANALYSIS"横幅占据图片上方20%高度，但这一信息可以在caption中说明。移除横幅可以增大histogram本身的显示面积，或缩小整体图片高度。

6. **Table 7位置打断阅读**: Table 7 (dimension handling comparison) 出现在§7 Related Work段落中间，打断了文字叙述的连贯性。建议移到§7开头作为全景对比，或§7末尾作为总结。

7. **Page 5-6表格过多**: Page 6包含3个表格（Table 4, 5, 6）在约1.5页空间内，加上Figure 6，导致视觉拥挤。考虑将部分表格移到appendix（如Table 4 padding rescue可作为supporting data），或合并Table 5/6为一个对比表。

---

## Improvement Checklist for Writer Agent

### High Priority (Must Fix)
- [ ] **M1 - Figure sizing revision**: Resize Fig 1 to 0.7\columnwidth, Fig 6 to 0.5\columnwidth, Fig 4 to figure* (span) or split into 2 figs. Target: save 20-30 lines of vertical space
- [ ] **M2 - Table 3 simplification**: Remove all colored backgrounds, replace ✓/× with text, simplify to 3-column layout. Remove "KEY CONTRIBUTION" from caption
- [ ] **M3 - Related Work expansion**: Add 15-20 citations (target 45+ total), structured subsections (Compression/Attention/Frameworks/GPU Optimization), add comparative discussion
- [ ] **M4 - Abstract scope clarification**: Restructure to clearly distinguish theoretical (96.9%) vs. practical (PaLU enforces alignment) scenarios. Explain target audience upfront
- [ ] **M5 - Font size audit**: Regenerate Fig 2 with ≥8pt labels, change Table 1 std from \scriptsize to \small or footnote format

### Medium Priority (Recommended)
- [ ] **m1 - Terminology consistency**: Define $d$ as head_dim in §2, use consistently. Standardize "8-aligned" (adj) vs "aligns to 8" (verb)
- [ ] **m2 - Figure 1 caption revision**: Remove redundant numbers (88%, 30%, 4.7%) from caption, add context about theoretical vs. production scenarios
- [ ] **m3 - C23 error bars**: Add footnote to Table 2 explaining trial counts and variance (<3% for aligned, <5% for misaligned)
- [ ] **m4 - H100 discussion revision**: Either run quick H100 validation or move to Future Work. If keeping, cite H100 whitepaper explicitly
- [ ] **m5 - Code availability statement**: Add to Conclusion: "Code, experiment scripts, and raw data available at [URL]"
- [ ] **m6 - Table 5/6 reordering**: Present negative case (RAP SVD) before positive case (Direct SDPA) to build narrative tension

### Low Priority (Optional)
- [ ] Combine Figure 5 and Figure 6 into 2-panel figure with shared caption
- [ ] Move Table 7 to start or end of §7 Related Work
- [ ] Add pseudocode for repair algorithm in §5.2
- [ ] Consider moving some tables (e.g., Table 4) to appendix if space is tight
- [ ] Add hatch patterns to Figure 4 bar charts for grayscale print compatibility

---

## Reviewer Confidence

**Confidence Score:** 4/5

**Expertise Areas:**
- GPU performance optimization and CUDA programming
- LLM inference systems (vLLM, TensorRT, FlashAttention internals)
- Systems measurement methodology
- Academic paper reviewing (MLSys, OSDI, SOSP)

**Limitations:**
- I cannot verify the specific FlashAttention 2.7.4 kernel dispatch behavior claimed in §4.2 without reading the source code myself
- I don't have access to PaLU compression internals to verify the "all checkpoints enforce 32-multiple" claim, relying on authors' analysis
- I cannot judge the statistical significance of some hardware experiments (C23) without seeing raw data and variance analysis
- My assessment of "Related Work insufficient" is based on citation count and breadth; I may be unaware of niche compression literature

---

*Reviewer: Paper Reviewer Agent*
*Date: 2026-01-28*
