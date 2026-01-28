# Paper Review: When Smaller Is Slower: Dimensional Collapse in Compressed LLMs

**Target Venue:** EuroMLSys (SIGPLAN format, 6 pages main content, references and appendix unlimited)
**Review Date:** 2026-01-28
**Reviewer:** Paper Reviewer Agent

---

## Summary

This paper investigates "dimensional collapse"—a phenomenon where post-training LLM compression produces irregular tensor dimensions (e.g., head_dim=107) that cause GPU performance degradation despite reducing FLOPs. The authors systematically diagnose three root causes on NVIDIA A100: Tensor Core tile misalignment (58% slowdown), vectorized load degradation (50% loss), and SDPA bandwidth inefficiency (40%). They disconfirm L2 cache waste (5.8%) as a significant factor.

The paper proposes a "dimension repair" strategy that pads irregular dimensions to alignment boundaries (8 or 16), achieving 22-28% kernel-level speedup with 3.7-7.2% memory overhead. Crucially, the paper provides an applicability framework (Table 3) that predicts when repair helps: it benefits direct compression methods (vanilla SVD) but not projection-based architectures (RAP SVD), validated through end-to-end experiments showing -0.8% for RAP SVD.

The work makes a valuable diagnostic contribution to the systems community by identifying and quantifying a previously overlooked performance cliff in LLM compression. The applicability framework is particularly useful for practitioners.

---

## Overall Rating

**Rating: Weak Accept (7.35/10)**

The paper addresses a relevant systems problem with solid experimental methodology. The diagnostic contribution is valuable, and the applicability framework adds practical utility. However, the scope is narrower than initially presented (96.9% misalignment only applies to theoretical analysis, not production checkpoints), and the end-to-end validation shows negative results for the tested architecture. The paper would benefit from clearer scope framing and additional compression methods that actually exhibit the problem.

**Confidence:** 4/5 (High confidence based on detailed analysis of claims, data, and figures)

---

## Detailed Scores

| Dimension | Weight | Score | Weighted |
|-----------|--------|-------|----------|
| Technical Quality | 40% | 7.5/10 | 3.00 |
| Paper Presentation | 30% | 7.0/10 | 2.10 |
| Innovation | 20% | 7.5/10 | 1.50 |
| Writing Quality | 10% | 7.5/10 | 0.75 |
| **Total** | 100% | - | **7.35/10** |

---

## Bottleneck Analysis (REQUIRED)

**主要瓶颈维度**: Paper Presentation

**瓶颈分数**: 7.0/10

**为什么是瓶颈**:
论文呈现是最薄弱的维度，具体原因如下：
1. 图表质量不一致——部分图表存在可读性问题（字体过小、坐标轴标签不清晰）
2. Figure 1（概览图）视觉元素过多，相互竞争注意力
3. 信息密度在各图表间差异较大——Figure 5/6 只有少量数据点却占用整栏宽度
4. 表格格式可以更专业（小数精度不一致、列对齐参差不齐）
5. 部分图表字体低于推荐的 8pt 最小可打印阅读阈值

**突破方向**:
由于 Paper Presentation 是瓶颈 (< 7.5)，应聚焦于改进视觉元素：
- 将所有图表字体增加到最低 8pt
- 简化 Figure 1 以减少视觉杂乱
- 考虑缩小 Figure 5/6 尺寸或增加数据点
- 标准化所有表格的格式和精度
- 使 Table 3（适用性框架）作为关键贡献更加醒目

**给 Planner 的建议**:
1. **视觉打磨 Pass**: 系统地将所有图表字体增加到最低 8pt
2. **Figure 1 重设计**: 简化概览图以聚焦核心洞察
3. **表格标准化**: 确保一致的小数精度（延迟 2 位小数）
4. **Table 3 突出**: 使关键的适用性框架表格更加醒目
5. **Figure 5/6 优化**: 缩小尺寸或增加数据点以提高信息密度

---

## Strengths

1. **清晰的问题定义**: 论文明确识别并阐述了"维度坍塌"问题——一个非直觉的现象，压缩可能导致减速而非加速。填补了压缩文献的空白。

2. **严谨的根因分析**: 跨三层（PyTorch 后端、CUDA 内核、硬件）的系统性调查，测试了四个假设，方法论扎实。排除 L2 缓存（5.8%）作为显著因素增加了科学严谨性。

3. **诚实的 Scope 澄清**: 论文值得称赞地对范围保持透明——澄清 96.9% 不对齐是理论值，而生产 PaLU checkpoint 是对齐的。这种知识诚信增强了可信度。

4. **经过验证的适用性框架**: Table 3 提供了何时应用 repair 的实用指南。RAP SVD 的负面结果（-0.8%）通过正确预测投影架构的不适用性验证了框架。

5. **可复现的实验**: 清晰的实验设置，包含具体版本（PyTorch 2.9.1, CUDA 12.8, FlashAttention 2.7.4），明确的方差报告（5-8%），每次测量多次试验。

---

## Weaknesses

1. **E2E 正面验证有限**: 内核级加速（22-28%）令人信服，但唯一的 E2E 验证案例（RAP SVD）由于其投影架构显示无收益。正面 E2E 案例将加强贡献。

2. **即时实用影响较窄**: 由于所有 24 个生产 PaLU checkpoint 已强制 32 倍数对齐，即时适用性仅限于"未来方法"或 vanilla SVD 场景。

3. **无 H100/H200 验证**: 所有实验仅在 A100 上进行。H100 影响的讨论纯属推测，没有经验验证。

4. **缺少下游任务评估**: 虽然 perplexity 已验证（bit-exact 保留声明得到支持），但全面的任务评估（MMLU 等）推迟到未来工作。

5. **图表质量问题**: 多个图表存在可读性问题（在视觉观察部分详述），降低了顶级会议期望的专业外观。

---

## Major Issues (Must Fix)

### M1. 图表字体尺寸低于可打印阅读阈值

**Location**: Figures 2, 5, 6 (Pages 3, 4, 5)

**Issue**: 视觉检查表明 Figure 2 的坐标轴标签和 Figure 5/6 的数据标签约为 6-7pt，低于推荐的 8pt 最小可打印阅读标准。

**Why it matters**: EuroMLSys 论文可能被打印或以缩小的缩放比例查看。小字体变得难以辨认，降低专业外观。

**Suggested Fix**:
- 将所有图表坐标轴标签增加到最低 8pt
- 将 Figure 5/6 的数据点标签（d=107, d=114 等）增加到 8pt
- 确保所有图表中的图例文本最低 8pt
- 通过在 PDF 中测量验证：文本在 72% 缩放时应 >= 6pt

### M2. Figure 1 视觉复杂性

**Location**: Page 2, Figure 1

**Issue**: Figure 1 试图在单个图形中传达过多信息。"(a) Dimensional Collapse Problem"和"(b) Dimension Repair Solution"面板包含太多相互竞争注意力的视觉元素（流程图、条形图、百分比标签、颜色编码）。

**Why it matters**: 作为第一张图，它为论文设定了基调。令人困惑的概览可能会阻止读者和审稿人深入参与。

**Suggested Fix**:
- 减少每个面板的视觉元素数量
- 全图使用更大、更清晰的字体
- 考虑是否所有注释都是必要的
- 确保颜色对比度对色盲读者足够

### M3. Figure 5 (E2E Performance) 与 Repair 无关

**Location**: Page 4, Figure 5

**Issue**: Caption 说"End-to-end performance: Baseline vs. PaLU... PaLU achieves 11.5× decode speedup"。但这个加速来自 KV cache 压缩减少内存带宽，与 dimension repair 无关（caption 末尾说"no dimension repair is needed"）。

**Why it matters**: 读者可能误以为 11.5x 来自 dimension repair。这混淆了论文的不同贡献。

**Suggested Fix**:
- 将 Figure 5 移到 Background 或 Related Work 作为 motivation
- 或添加一个真正展示 dimension repair E2E 效果的图（使用 vanilla SVD）
- 或修改 caption 明确说明这与 repair 无关，强调是 KV cache 压缩的收益

### M4. 作者姓名疑似拼写错误

**Location**: Page 1, Author list

**Issue**: 第二作者"Tian Lvy"可能是"Tian Lyu"或"Tian Lv"的拼写错误。代码中有 TODO 注释指出这一问题。

**Why it matters**: 作者姓名错误是严重的专业性问题，会出现在最终版和引用记录中。

**Suggested Fix**: 确认正确拼写并修正。

---

## Minor Issues (Suggested)

### m1. Figure 5/6 标签聚集

**Location**: Page 4-5, Figures 5, 6
**Issue**: Figure 6 的散点图标签（d=107, d=114, d=117, d=121, d=125）聚集在上方区域，可能重叠。
**Suggestion**: 调整标签位置使用偏移或引导线改善可读性。

### m2. Table 1 标准差格式不一致

**Location**: Page 3, Table 1
**Issue**: 标准差表示法使用不一致的小数位数（±.03 vs ±.20）。
**Suggestion**: 全部标准化为 2 位小数（例如 ±0.03 和 ±0.20）。

### m3. Table 3 视觉突出性

**Location**: Page 4, Table 3
**Issue**: Table 3（适用性框架）是论文的关键贡献之一，但在视觉上与其他表格没有区别。
**Suggestion**: 考虑更大的 Yes/No 单元格、加粗文本或轻微背景阴影，以强调这个关键的从业者指南表格。

### m4. Figure 5/6 信息密度

**Location**: Pages 4-5, Figures 5, 6
**Issue**: Figure 5 只有 4 根柱子，Figure 6 只有 6 个数据点，但都占用整栏宽度。信息密度相对较低。
**Suggestion**: 考虑将 Figure 5/6 尺寸减少到 0.8 栏宽，或与相关表格数据合并以增加信息密度。

### m5. 表格小数精度一致性

**Location**: All tables
**Issue**: 延迟值使用不同精度（例如 2.064 vs 1.490 vs 27.8%）。
**Suggestion**: 标准化延迟为 2 位小数（1.49ms），加速为 1 位小数（27.8%）。

### m6. Section 6.7 Limitations 可见性

**Location**: Page 6, Section 6.7
**Issue**: Scope 和 Limitations 很重要但不够突出。
**Suggestion**: 考虑使用编号列表或小表格格式以获得更好的可见性。

### m7. H100 预期声明缺乏支撑

**Location**: Page 6-7, Section 8 Conclusion
**Issue**: "we expect similar dimensional collapse on H100/H200"但没有任何 H100 数据支持。
**Suggestion**: 删除此声明，或修改为"H100 validation is future work"。

---

## Questions for Authors

1. **关于 E2E 验证**: 是否有计划测试 vanilla SVD 压缩（无对齐约束）的 E2E 性能？这将直接验证 dimension repair 的价值。

2. **关于 RAP SVD**: 能否量化 repair 对 GEMM 层的加速？即使 SDPA 不受益，投影层（k_proj_A/B）可能显示可测量的改进。

3. **关于 PaLU 对齐策略**: PaLU 为什么选择 32-multiple 对齐？是否考虑过更细粒度的对齐（如 8 或 16）？

4. **关于 96.9% 统计**: 512 KV head dimensions 来自哪些模型/层？这个统计是否对 Fisher rank allocation 的参数敏感？

5. **FlashAttention 版本**: 是否测试过 FlashAttention-3 在 H100 上的表现？结果会显著改变吗？

---

## Detailed Comments by Section

### Abstract
总体良好，包含具体的量化声明（88% 延迟增加，22-28% 内核级加速，3.5-5.9x ROI）。"architecture-dependent"限定语适当。理论 vs. 生产的 scope 澄清存在但可以更突出。

### Introduction
写作清晰，问题陈述明确。"Scope and Applicability"段落至关重要且诚实。贡献列表具体且可验证。96.9% 数字的"theoretical"性质现在标注清晰。

### Background (Section 2)
对 Tensor Core 对齐、FlashAttention 约束和低秩压缩的覆盖充分。FlashAttention 2.7.4 的版本说明有价值。可以简要解释为什么 MEM_EFFICIENT 比 FLASH 有更严格的 8-alignment 要求。

### Dimensional Collapse (Section 3)
强实验方法论，包含具体版本和方差确认（5-8% 运行间变异）。Figure 2/3 的"THEORETICAL ANALYSIS"横幅有效传达了 scope。后端选择行为分析有洞察力。

### Root Cause Analysis (Section 4)
**最强的章节。** 跨三层（PyTorch 后端、CUDA 内核、硬件）的分析系统且执行良好。Table 2 有效总结了假设状态。发现 L2 缓存（5.8%）不是主因，防止从业者追求死胡同优化。

### Shape-Aware Compression (Section 5)
Shape Contract 的形式化简洁清晰。MINIMAL（8-aligned）vs. OPTIMAL（16-aligned）策略区分实用。bit-exact 输出保留保证建立部署信心。

### Evaluation (Section 6)
- Section 6.1（适用性框架）：关键贡献 - Table 3 提供优秀的从业者指南
- Section 6.2-6.4：强内核级验证，统计报告适当
- Section 6.5（RAP SVD E2E）：尽管是"负面"结果，但有价值的架构洞察
- Section 6.6（准确性）：Perplexity 验证良好；下游任务标注为未来工作
- Section 6.7（限制）：诚实且放置适当

### Related Work (Section 7)
覆盖全面。Table 7 比较各系统的维度处理对从业者有价值。

### Conclusion (Section 8)
适当总结了发现。H100 影响明确标记为推测。集成指南实用。

---

## Visual Observations (必填！)

### Page-by-Page Observations

**Page 1:**
- **看到的内容**: 标题"When Smaller Is Slower: Dimensional Collapse in Compressed LLMs"，5 位作者（Jihao Xin, Tian Lvy, Qilong Pan, Kesen Wang, Marco Canini），来自 KAUST 和 HUMAIN AI 的机构，Abstract，Keywords
- **具体观察**:
  - 标题清晰且信息丰富
  - Abstract 密集但全面（约 200 词）
  - Keywords 包括："LLM Compression, GPU Optimization, Tensor Core, Memory Alignment"
  - 作者"Tian Lvy"拼写看起来不寻常
- **问题/建议**:
  1. 作者姓名"Tian Lvy"应验证——可能是"Tian Lyu"的拼写错误
  2. Abstract 信息密集，内联代码片段（head_dim=107）看起来稍显拥挤

**Page 2:**
- **看到的内容**: Introduction 结尾，Figure 1"Dimensional collapse overview"包含 (a) problem 和 (b) solution 面板
- **具体观察**:
  - Figure 1(a) 展示流程："Original (d=128)" → "compress" → "88%" → SDPA slow path
  - Figure 1(b) 展示："d=107" → "repair" → "d=112"，带"+30%"性能标注
  - 颜色编码：绿色表示对齐，黄色/橙色表示中间状态，红色表示问题
  - 可见多个百分比标注：88%, 30%, 4.7%
  - 底部框架区分理论 vs 生产场景
- **问题/建议**:
  1. Figure 1 视觉繁忙，有许多竞争元素（流程箭头、百分比、条形图、标签）
  2. 部分标注文本约为 6pt（较小）
  3. 绿色和黄色/金色之间的颜色对比度可以改进以提高可访问性

**Page 3:**
- **看到的内容**: Figure 2"SDPA latency across head dimensions"，Figure 3"Dimension distribution"（实际论文中是 fig3_palu_dist），Table 1"SDPA backend latency"
- **具体观察**:
  - Figure 2：折线图，X 轴"Head Dimension"（范围约 80-160），Y 轴"Latency (ms)"（约 1.0-2.5ms）
  - 清晰可见的阶梯模式：8-aligned 维度聚集在约 1.1-1.6ms，misaligned 在约 1.6-2.2ms
  - 图例显示"8-aligned"（蓝色）和"Misaligned"（橙色）
  - Figure 3：直方图，顶部有醒目的黄色"THEORETICAL ANALYSIS"横幅
  - 显示统计数据："Aligned: 3.1%"，"Misaligned: 96.9%"
  - 底部绿色注释："Note: All 24 production PaLU checkpoints enforce 32-multiple alignment"
  - Table 1：显示 dims 96, 104, 107, 112, 128 跨 AUTO/FLASH/MEM_EFF/MATH 后端
  - d=107 行加粗，MEM_EFF 显示"N/A*"带脚注
- **问题/建议**:
  1. Figure 2 坐标轴标签约为 7pt（打印边界）
  2. Figure 3 横幅醒目但直方图条形较细且颜色较浅
  3. Table 1：标准差表示法不一致（±.03 vs ±.20）
  4. Table 1 脚注"*MEM_EFFICIENT unavailable: requires strict 8-alignment"非常小

**Page 4:**
- **看到的内容**: Figure 4"Root cause breakdown"，Table 2"Hardware layer root cause analysis"，Section 5"Shape-Aware Compression"，Table 3 开始，Figure 5"E2E performance"
- **具体观察**:
  - Figure 4：水平条形图显示 4 个根因
  - "Tensor Core"条：58%（最长），标记为橙色"Confirmed"
  - "Vectorized Loads"：50%，"Confirmed"
  - "SDPA Bandwidth"：40%，"Confirmed"
  - "L2 Cache"：5.8%（短条），标记为灰色"Not Confirmed"
  - Table 2：紧凑的 4 行表格，列：Hypothesis, Status, Impact, Root Cause
  - Table 3：三种架构类型，带彩色 Yes/No/N/A 单元格
  - Figure 5：柱状图比较"Baseline"vs"PaLU"的 Prefill 和 Decode 吞吐量
  - Prefill 柱：约 9000-10000 tok/s，带"-2.0%"标注
  - Decode 柱：约 100-1400 tok/s，带"11.5x"加速标注
- **问题/建议**:
  1. Figure 4：显示百分比在条形和轴上有些冗余
  2. Figure 4："Not Confirmed"灰色可以与其他颜色更明显区分
  3. Figure 5：Prefill（约 10000）和 Decode（约 100-1400）之间的比例差异造成视觉失衡
  4. **Figure 5 关键问题**：11.5x 加速与 dimension repair 无关，来自 KV cache 压缩

**Page 5:**
- **看到的内容**: Table 4"Padding rescue results"，Figure 6"Speedup vs memory overhead tradeoff"，Table 5"SDPA latency before and after repair"，Table 6"RAP SVD E2E validation"
- **具体观察**:
  - Table 4：从 d=107 padding 到 112（4.7% 开销，1.39x）和 128（19.6%，1.37x）
  - Figure 6：散点图，X："Memory Overhead (%)" 0-10%，Y："Speedup (%)" 0-30%
  - 数据点标签：d=107, d=114, d=117, d=120, d=121, d=125
  - d=120 在原点高亮，带"already 8-aligned"标注
  - ROI 标注："Average ROI: MINIMAL 5.9x (22%/3.7%), OPTIMAL 3.5x (25%/7.2%)"
  - Table 5：6 个维度（107, 114, 117, 120, 121, 125）带 Original/Minimal/Optimal 列
  - d=107：2.064ms → 1.490ms (+27.8%)
  - d=120：1.557ms → 1.557ms (0%) - 验证对齐假设
  - Table 6：RAP SVD 结果显示无收益
  - Prefill：290.5 → 292.9 (-0.8%)
  - Decode：1009 → 1000 (-0.9%)
- **问题/建议**:
  1. Figure 6：数据标签约 6-7pt（太小）；标签在左上区域聚集
  2. Figure 6：只有 6 个点但占用整栏宽度（信息密度低）
  3. Table 5：小数精度不一致（ms 3 位小数，% 1 位小数）
  4. Table 6：小负数（-0.8%，-0.9%）重要但容易被忽视

**Page 6:**
- **看到的内容**: Section 6.7 Scope and Limitations，Section 7 Related Work，Table 7"Dimension handling comparison"
- **具体观察**:
  - Limitations 有 3 个编号条目，格式清晰
  - Related Work 分为 4 个段落：LLM Compression, KV Cache & Attention, Inference Frameworks, Positioning
  - Table 7：跨栏，比较 7 个系统（FlashAttn-2, vLLM, TensorRT, GPTQ/AWQ, PaLU, RAP SVD, This work）
  - FlashAttn-2："Optimized: 32,64,96,128,256" - "Slow path (+30-45%)"
  - vLLM："64,80,96,112,128,256" - "Error/fallback"
  - PaLU："32-multiple (enforced)" - "N/A (aligned)"
  - RAP SVD："Any integer" - "Affected"
  - "This work"："Repair to 8/16-multiple" - "Compile-time fix"
- **问题/建议**:
  1. Related work 段落密集，每句有许多引用
  2. Table 7："Misaligned handling"列条目长度/详细程度不一

**Page 7:**
- **看到的内容**: Section 8 Conclusion，References 开始
- **具体观察**:
  - Conclusion 有 4 个加粗子段落：Diagnostic contribution, Validated applicability framework, H100 Implications, Integration with compression frameworks
  - References 使用 ACM 格式，编号 [1]-[26]
  - 关键引用可见：FlashAttention, GPTQ, AWQ, PaLU, RAP, vLLM, TensorRT
- **问题/建议**:
  1. "H100 Implications"段落声称预期类似行为，但没有数据支持

**Page 8:**
- **看到的内容**: References 续
- **具体观察**:
  - 继续 [21] 到 [26] 的引用
  - 页面大部分空白（只有约 1/4 页内容）
  - 最后一条引用是 [26] CALDERA
- **问题/建议**:
  - 正常的 references 页，空白合理
  - 论文总长度约 6 页正文 + 1.5 页 references，符合 EuroMLSys 要求

### Figure-by-Figure Assessment

| Figure | 位置 | 你观察到的具体内容 | 尺寸评估 | 布局评估 | 问题 |
|--------|------|-------------------|---------|---------|------|
| Fig 1 | Page 2 | 跨栏 overview，(a) 展示维度坍塌导致 +88% latency，(b) 展示 repair 恢复 30%，4.7% overhead。流程图、条形图、百分比标注。颜色编码路径。 | 合适 | 正常 | 视觉元素过多；部分标签约 6pt；颜色对比度可更强 |
| Fig 2 | Page 3 | 折线图：X "Head Dimension" (80-160)，Y "SDPA Latency (ms)" (1.0-2.5)。两条线（8-aligned 蓝色，Misaligned 橙色）。阶梯模式清晰。 | 合适 | 正常 | 坐标轴标签约 7pt（边界）；图例标记小 |
| Fig 3 | Page 3 | 直方图：维度分布。黄色"THEORETICAL ANALYSIS"横幅带"3.1% aligned, 96.9% misaligned"。底部绿色注释关于生产 PaLU 对齐。 | 合适 | 正常 | 直方图条形细且颜色浅；横幅有效但密集 |
| Fig 4 | Page 4 | 水平条：TC 58%, Vec 50%, SDPA BW 40%, L2 5.8%。橙色"Confirmed"，灰色"Not Confirmed"。 | 合适 | 正常 | 轻微冗余（% 在条形和轴都显示）；"Not Confirmed"可更明显 |
| Fig 5 | Page 4 | 柱状图：Baseline vs PaLU 的 Prefill（约 10000 tok/s）和 Decode（约 100-1400）。"-2.0%"和"11.5x"标注。 | 合适 | 正常 | Prefill/Decode 比例失衡；**11.5x 与 repair 无关** |
| Fig 6 | Page 5 | 散点图：X "Memory Overhead %" (0-10)，Y "Speedup %" (0-30)。MINIMAL（圆）和 OPTIMAL（方）。d=120 在原点高亮。ROI 标注框。 | **可更小** | 正常 | 标签约 6-7pt 太小；只有 6 点（密度低）；标签聚集 |

### Table Assessment

| Table | 位置 | 观察到的具体内容 | 问题 |
|-------|------|------------------|------|
| Table 1 | Page 3 | Backend latency：d=96,104,107,112,128 × AUTO/FLASH/MEM_EFF/MATH。d=107 加粗。MEM_EFF="N/A*"。带 std 的延迟（如 1.17±.03）。 | Std 表示法不一致（±.03 vs ±.20）；脚注文本很小 |
| Table 2 | Page 4 | Root causes：H1-H4 带 Status/Impact/Root Cause。3 Confirmed，1 Not Confirmed。 | 紧凑有效；"Root Cause"条目简洁 |
| Table 3 | Page 4 | Applicability：Direct=Yes(+25-28%)，Projection=No(-0.8%)，Quantization=N/A。彩色单元格。 | 关键表格但视觉不突出；彩色框稍显不正式 |
| Table 4 | Page 5 | Padding rescue：d=107→112 (4.7%, 1.39x)，→128 (19.6%, 1.37x)。 | 清晰且格式良好 |
| Table 5 | Page 5 | Repair：6 dims × Original/Minimal/Optimal 带 deltas。d=120 显示 0%（验证）。 | 精度不一致（ms 3 位小数，% 1 位小数） |
| Table 6 | Page 5 | RAP SVD E2E：Prefill -0.8%，Decode -0.9%，Memory +0.1%。 | 重要的负面结果但平淡呈现 |
| Table 7 | Page 6 | Dimension handling：7 个系统比较。支持范围 + misaligned handling。 | 条目长度不一；总体信息丰富 |

### Layout Assessment (布局评估)

**整体页面利用率**：
- Pages 1-6（主要内容）：密度良好，适合 SIGPLAN 格式
- 未观察到大片未使用空白
- 图表与文本流整合良好

**图文冲突检查**：
- 未发现图片侵入文本边距
- 所有图片与 caption 有足够间距（估计 3-5mm）
- 未检测到图片与文本重叠问题
- 双栏格式正确遵守

**尺寸优化机会**：

| 图片 | 问题类型 | 描述 | 建议修改 |
|------|---------|------|---------|
| Fig 5 | 信息密度偏低 | 只有 4 根柱子占用整栏 | 可缩小到 0.8 栏宽 |
| Fig 6 | 信息密度低 | 只有 6 个数据点占用整栏 | 缩小到 0.7 栏宽或与 Table 4 合并 |

### Visual Issues Summary

**已识别的 10 个视觉问题**：

1. **Page 1, 作者列表**: "Tian Lvy"看起来是拼写错误——应验证正确拼写（可能是"Tian Lyu"）

2. **Page 2, Figure 1**: 视觉复杂——太多竞争元素（流程图、条形图、百分比、标签）。部分标注文本约 6pt。

3. **Page 3, Figure 2**: 坐标轴标签约 7pt，处于 8pt 最小打印可读性推荐的边界。

4. **Page 3, Table 1**: 标准差表示法不一致（±.03 vs ±.20）——应标准化为 2 位小数。

5. **Page 3, Table 1 脚注**: "*MEM_EFFICIENT unavailable"脚注文本非常小，容易被忽视。

6. **Page 4, Figure 5**: Prefill（约 10000）和 Decode（约 100-1400）之间的比例差异造成视觉失衡。**更重要的是，11.5x 加速与 repair 无关**。

7. **Page 5, Figure 6**: 数据点标签（d=107, d=114 等）约 6-7pt，低于 8pt 最小值。标签在左上区域聚集。

8. **Page 5, Figure 6**: 信息密度低——整栏图只有 6 个点。可以更小。

9. **Page 4, Table 3**: 关键适用性框架表格与其作为贡献的重要性相比缺乏视觉突出性。

10. **Page 5, Tables 5-6**: 延迟值和百分比的小数精度不一致。

---

## Improvement Checklist for Writer Agent

### High Priority (Must Fix)
- [ ] **M1**: 将 Figure 2 坐标轴标签字体增加到最低 8pt
- [ ] **M1**: 将 Figure 6 数据点标签字体增加到最低 8pt
- [ ] **M2**: 简化 Figure 1——减少视觉元素，增加字体尺寸
- [ ] **M3**: 修改 Figure 5 的 caption 或移到 Background，明确说明 11.5× 与 repair 无关
- [ ] **M4**: 修正作者姓名拼写错误"Tian Lvy"→ 验证正确拼写

### Medium Priority (Recommended)
- [ ] **m1**: 调整 Figure 6 标签位置以减少聚集
- [ ] **m2**: 标准化 Table 1 std 表示法为 2 位小数（±0.03, ±0.20）
- [ ] **m3**: 使 Table 3 更视觉突出（加粗 Yes/No，更大单元格）
- [ ] **m4**: 考虑缩小 Figure 5/6 尺寸或增加数据点
- [ ] **m5**: 标准化所有表格的小数精度
- [ ] **m7**: 删除或修改 H100 预期声明
- [ ] 平衡 Figure 5 比例（考虑对数刻度或分离面板）

### Low Priority (Optional)
- [ ] 稍微增加 Table 1 脚注字体尺寸
- [ ] 考虑重新框定 Table 6 负面结果的呈现
- [ ] 将 Section 6.7 limitations 格式化为编号列表
- [ ] 系统验证所有图表字体满足 8pt 最小值
- [ ] 确保 Table 7 术语与 Table 3 一致

---

## Data Verification Summary

**论文声明 vs. findings.yaml 中的证据**：

| 论文中的声明 | findings.yaml 中的来源 | 状态 |
|-------------|----------------------|------|
| 88% latency increase (d=107 vs d=96) | F1.1: "2.147ms vs 1.140ms" | 已验证 |
| 12.6x Math vs Flash backend | F1.2: "26.995ms vs 2.139ms" | 已验证 |
| 96.9% misaligned (theoretical) | C4 details: palu_dims_distribution | 已验证（理论值） |
| 58% Tensor Core slowdown | F2.3.1: tc_utilization 30%→12% | 已验证 |
| 50% vectorized load loss | F2.3.3: float4 73-83 TFLOPS vs scalar 39-40 | 已验证 |
| 40% SDPA bandwidth loss | F2.3.4: 153-160 GB/s vs 107-118 GB/s | 已验证 |
| 5.8% L2 cache (negligible) | F2.3.2: "5.8% sector waste" | 已验证 |
| 22-28% kernel speedup | F4.2: benchmark_speedups | 已验证 |
| 3.72-7.2% memory overhead | F4.2: actual_overhead | 已验证 |
| RAP SVD -0.8% (no benefit) | F5.8: prefill_results | 已验证 |
| All 24 PaLU checkpoints aligned | c5_status_summary | 已验证 |

**所有主要声明都有 findings.yaml 中的实验支持。**

---

## Reviewer Confidence

**Confidence Score:** 4/5

**Expertise Areas:**
- GPU 优化和 CUDA 编程
- 注意力机制和 transformer 架构
- LLM 压缩技术
- 系统性能评估方法论

**Limitations:**
- 无法在没有实验的情况下验证 H100/H200 推测
- 无法在没有源码分析的情况下完全验证 FlashAttention 内部内核行为
- paper_example 参考论文不可用于比较
- 无法运行实验验证可重复性

---

## Score Improvement Guidance

**当前总分: 7.35/10**

达到 **7.5/10**（稳固的 Weak Accept）：
1. 修复图表字体尺寸满足 8pt 最小值（+0.15 Presentation）

达到 **8.0/10**（Accept）：
1. 以上所有 presentation 修复
2. 添加使用 vanilla SVD 压缩的正面 E2E 验证（+0.4 Technical Quality）
3. 整体加强图表质量（+0.25 Presentation）

达到 **8.5/10**（Strong Accept）：
- 以上所有改进
- H100 验证数据
- 下游任务评估（MMLU 等）

---

## 附录：分数趋势分析

当前分数：7.35/10，与之前 6 次迭代基本持平。

**停滞原因分析**：
论文的主要瓶颈（Paper Presentation 7.0/10）在过去迭代中没有实质性改进。图表质量问题（字体过小、信息密度不一致）是可以通过技术手段解决的。

**突破瓶颈的路径**：
1. **短期可行**：改进图表质量（字体、尺寸、一致性）→ 可提升 Presentation 到 7.5-8.0
2. **中期可行**：添加正面 E2E 验证（vanilla SVD）→ 可提升 Technical Quality 到 8.0+
3. **长期**：H100 验证 + 下游任务评估 → 达到 Strong Accept 水平

如果无法获得正面 E2E 结果，应考虑重新定位论文为"诊断研究"（diagnostic study），强调问题的发现和根因分析，弱化"dimension repair 解决方案"的贡献声明。

---

*Reviewer: Paper Reviewer Agent*
*Date: 2026-01-28*
