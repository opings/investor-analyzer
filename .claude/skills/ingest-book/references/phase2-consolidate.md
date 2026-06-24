# ingest-book · Phase 2：整理沉淀（每年 PDF 读完后，1-2 小时）

## 2.1 产物清单

| 输入 | 输出 | 处理方式 |
|------|------|----------|
| `posts/YYYY-DRAFT.md` | `posts/YYYY.md` | 去过程草稿（frontmatter status、"待补"标记、调试痕迹），保结构化笔记 |
| 已存在 `style.md` | `style.md` 末尾 `## YYYY 新增` section | 只记 YYYY 新出现的画像点，不重复 |
| 已存在 `playbook.md` | `playbook.md` 末尾 `## YYYY 新增` section | 同上，只记新工具/口诀/反向案例 |
| DRAFT 时间线表 | `holdings/YYYY-持仓变化.md` | 抽出持仓行（如适用）|
| 文章公开预测 | `calls/YYYY-calls.md` | 抽出对未来的判断 + 后续验证（如适用，触发 [[backtest-call]]） |
| 本年所有新立场 | **`current-view.md`（收敛刷新）** | ★ 读完一年后**重写而非追加**：把本年演化反映进"当前有效版"，旧立场移进"已废弃/已演化"表。这是 style.md（演化史）的对照收敛层 |
| 本年覆盖情况 | **`coverage.md`（更新热力图）** | ★ 把本年的月度有/无数据填进热力图，登记新发现的空洞 |

## 2.2 整理标准

**`posts/YYYY.md`**：
- 去掉 DRAFT 的 frontmatter，保留简版（year / source / article_count / highlights）
- 文章顺序不变，section 结构不变
- 去掉"待补"、调试 grep 残留等过程产物

**`style.md` 增量 section**：
- 新增 `## YYYY 新增` 大节
- 子节对齐：投资框架 / 估值方法 / 选股偏好 / 市场观 / 风险偏好 / 标志性判断 / 关键人物
- 仅写 YYYY 出现的新内容，不复述已有

**`playbook.md` 增量 section**：
- 新增 `## YYYY 新增` 大节
- 子节对齐：工具 / 口诀 / 反向案例 / 避雷清单
- 每条带 #N 文章引用

**`current-view.md` 收敛刷新（区别于上面的"追加"）**：
- style/playbook 是**追加** `## YYYY 新增`；current-view 是**重写收敛**
- 把本年新立场更新进"当前有效版"各节（估值/选股/仓位/市场观/能力圈）
- 本年改了卦的旧立场 → 移入"已废弃/已演化"表，注明何时演化 + 指回 style.md 年份
- 更新顶部"截至日期"
- 模板见 `knowledge/gurus/_template/current-view.md`

**`coverage.md` 更新**：
- 把本年 1-12 月填 `✓/◐/✗`
- 新发现的空洞写进"已知空洞"
- 更新覆盖统计（总篇数/年份）

## 2.3 完成后

- READING_STATE 对应 block 移到 `## [已完成]` 节
- 保留 DRAFT.md 作为审计草稿（不删，不动）
- 提交 git（若该项目启用了 git）
