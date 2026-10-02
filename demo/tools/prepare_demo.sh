#!/usr/bin/env bash
# 把 output/band/ 里的精灵表和 manifest 拷贝到 demo/src/common/,
# 让 AIoT-IDE 能直接打开 demo/ 编译打包。
#
# 用法:
#   bash demo/tools/prepare_demo.sh            # 默认 band 档
#   bash demo/tools/prepare_demo.sh band-lite   # 改用 lite 档
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PRESET="${1:-band}"
SRC="$ROOT/output/$PRESET"
DEST="$ROOT/demo/src/common"

if [[ ! -d "$SRC" ]]; then
  echo "源目录不存在: $SRC (请先 python3 tools/convert_sprites.py)" >&2
  exit 1
fi

mkdir -p "$DEST"
# 拷贝需要的图集: tiles0 (地图) + warrior (角色) + items (道具, 留作扩展)
cp -f "$SRC/tiles0.png"  "$DEST/"
cp -f "$SRC/warrior.png" "$DEST/"
cp -f "$SRC/items.png"   "$DEST/"
cp -f "$SRC/sprites.js"  "$DEST/"

echo "已准备 $PRESET 档 demo 资源 -> $DEST"
ls -la "$DEST"