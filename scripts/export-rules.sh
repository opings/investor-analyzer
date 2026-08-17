#!/usr/bin/env bash
# ============================================================
# 导出「抽象规则」到 investor-framework 规则库（镜像 + commit + push）
# ============================================================
# 用法：bash scripts/export-rules.sh
#
# 真源：主库（investor-analyzer）。规则库是只读镜像，
#       不要直接在规则库改文件 —— 改主库，再跑本脚本。
# 范围：scripts/rules-manifest.txt 白名单（唯一权威）。
# 语义：全量镜像 —— 规则库里除自有文件（README/LICENSE/.gitignore）外
#       全部重建，主库的删除/改名自动收敛。
# 位置：规则库默认在主库同级 ../investor-framework，
#       可用环境变量 INVESTOR_FRAMEWORK_DIR 覆盖。

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${INVESTOR_FRAMEWORK_DIR:-$(cd "$SRC/.." && pwd)/investor-framework}"
MANIFEST="$SRC/scripts/rules-manifest.txt"

# 规则库自有文件（导出永不触碰）
KEEP=(".git" "README.md" "LICENSE" ".gitignore")

[ -f "$MANIFEST" ] || { echo "❌ 找不到白名单：$MANIFEST"; exit 1; }
[ -d "$DEST/.git" ] || { echo "❌ 规则库不存在或不是 git 仓库：$DEST"; exit 1; }

# 规则库必须干净（这里不该有手工改动 —— 规则一律改主库）
if [ -n "$(git -C "$DEST" status --porcelain)" ]; then
  echo "❌ 规则库有未提交改动，先处理掉再导出："
  git -C "$DEST" status --short
  exit 1
fi

# 远端若有新提交（如网页端改了 README），先快进拉平；空库/无上游时忽略
git -C "$DEST" pull --ff-only --quiet 2>/dev/null || true

# 1) 清空受管内容（KEEP 自有文件除外）→ 主库的删除/改名得以收敛
keep_args=()
for k in "${KEEP[@]}"; do keep_args+=(! -name "$k"); done
find "$DEST" -mindepth 1 -maxdepth 1 "${keep_args[@]}" -exec rm -rf {} +

# 2) 按白名单复制（-R 保持相对路径；目录 = 整棵子树）
copied=0
dirty=""
while IFS= read -r entry; do
  case "$entry" in ''|'#'*) continue ;; esac
  entry="${entry%/}"
  if [ ! -e "$SRC/$entry" ]; then
    echo "⚠️  白名单条目不存在，跳过：$entry"
    continue
  fi
  rsync -aR --exclude '.DS_Store' "$SRC/./$entry" "$DEST/"
  copied=$((copied + 1))
  # 规则文件本身有未提交改动时，commit message 标 +dirty
  if [ -z "$dirty" ] && [ -n "$(git -C "$SRC" status --porcelain -- "$entry")" ]; then
    dirty="+dirty"
  fi
done < "$MANIFEST"

[ "$copied" -gt 0 ] || { echo "❌ 白名单没有任何有效条目"; exit 1; }

# 3) commit + push（无变更则安静退出）
git -C "$DEST" add -A
if git -C "$DEST" diff --cached --quiet; then
  echo "✅ 规则库已是最新，无需同步。"
  exit 0
fi

src_hash="$(git -C "$SRC" rev-parse --short HEAD)"

echo "—— 本次同步变更 ——"
git -C "$DEST" diff --cached --stat

git -C "$DEST" commit --quiet -m "sync from investor-analyzer@${src_hash}${dirty}"
if ! git -C "$DEST" push --quiet origin HEAD; then
  echo "❌ push 失败（远端可能有新提交，比如网页端改了 README）。"
  echo "   到规则库 git pull --rebase 后 git push，或处理完再重跑本脚本。"
  exit 1
fi
echo "✅ 已同步并推送：investor-framework ← investor-analyzer@${src_hash}${dirty}"
