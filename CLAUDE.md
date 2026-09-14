# CLAUDE.md · 协作约定

> 给 **Claude Code 和人类协作者**共用。Claude Code 每次会话自动加载本文件。
> 仓库是什么、目录怎么分、什么能入 git —— 见 `README.md`。**本文件只讲「改动怎么提交」。**

---

## 提交流程：走 PR，不直接 push `main`

```bash
git switch -c <按内容命名的分支>      # 从 main 切
git add <...> && git commit           # 一个 commit 一件事
git push -u origin <branch>
gh pr create                          # 到这里停下，等人看过 diff
# review 通过 → 合并(rebase) → 删分支 → git switch main && git pull
```

**为什么不直接 push main**：GitHub 上 `main` 挂着 ruleset `Branch Protection`，三条规则在生效 ——

| 规则 | 作用 |
|---|---|
| `pull_request` | 改动必须经由 PR（**批准数 = 0**：单作者库里 GitHub 不允许作者批准自己的 PR，留着 ≥1 会让每个 PR 永远卡在「等待批准」；PR 的价值在这里是 **diff 审阅面 + 变更记录**，不是不存在的第二双眼睛） |
| `deletion` | 禁止删除 `main` |
| `non_fast_forward` | 禁止对 `main` force push |

repo admin 能绕过，但**绕过不是流程** —— 直接 push 会返回 `remote: Bypassed rule violations`，那是警告不是许可。

**合并方式用 `rebase`**（三种都开着）。`main` 的历史**全线性、零 merge commit**，rebase 既保持线性、又保留「一个 commit 一件事」的粒度；`squash` 会把多 commit 压成一个，`merge` 会开始产生 merge commit。

---

## 🔴 分支必须短命 —— 这是本库的机制约束，不是洁癖

后台哨兵（launchd `com.investor.daily-news`，工作日 16:00 跑 `scripts/daily-news.sh`）**无条件往工作区写** `knowledge/daily/` 与 `knowledge/companies/`。它自己不 commit，只落文件 —— 所以**你停在哪个分支，哪个分支就吸收它的产物**。

长命分支会自动跑偏，不需要谁犯错：

> **实证**：`feat/tesla-build` 活了三天（2026-09-11 建 → 09-14 合），累积 9 个 commit，**只有 2 个跟特斯拉有关**，其余 7 个是 coinbase / circle / AGC / 云铝 / 华致 / google / 拼多多 / 日报。分支名到最后已经描述不了自己的内容。

纪律三条：

1. **一个分支一个主题**，开始新主题前先把上一个 PR 合掉
2. **同会话开、同会话合**，别过夜
3. 万一已经混进无关内容：**按主题拆开重提**，或在 PR 描述里如实列出实际包含什么 —— 别硬凑一个标题去盖它

分支命名按**内容本质**，不按工作流角色（`judgment/tesla-too-hard` ✅ / `feature-2` ❌）。

---

## 开工前的一次性检查

`git push` 通 **≠** `gh` 能建 PR —— 两者可能是**不同身份**：`git` 走 remote 里配的协议（本仓库用 SSH），`gh` 走它自己的 OAuth token。二者可以分属不同 GitHub 账号，且这种割裂平时不会暴露。

```bash
gh repo view --json nameWithOwner,viewerPermission
```

期望 `WRITE` 或 `ADMIN`。若是 `READ`，`gh pr create` 会失败 —— 用 `gh auth login` 换成有写权限的账号（多账号可共存，`gh auth switch` 切换）。

---

## 落盘纪律（详见 README，此处只列最容易踩的）

- **任何含本机绝对路径（`/Users/<用户名>/...`）或个人密钥的内容都不入库。**
- 源档（`report/`、`finance/**/年报季报/`）、机器专属自动化（`daily-news.sh`、`.plist`）、工作文件（`*-DRAFT.md`、`READING_STATE.md`）一律不入 git。
- 新增大类文件前拿不准 → 先 `git status` 看一眼会带进什么。
