#!/usr/bin/env bash
#
# gen.sh — 一键从解包目录生成消费方要的全部生成物(见 docs/data.md)
#
# 顺序:unpack.sh 增量解包(--no-unpack 跳过)→ gen_gamedata(names.json)→ gen_images / gen_icons
# (→ gen_bigmap,capture 档)→ gen_pbdesc(给了 --pbdesc 或默认档时)→ gen_proto(给了 --pb 时)。
# 生成物不进本仓库:默认落到 ./build/;消费方(如 rocom-capture)的 Makefile 把它们指到
# 自己 go:embed 的目录。
#
# 用法:
#   ./scripts/gen.sh                                   # 全量档 → build/{gamedata,pbdesc}
#   ./scripts/gen.sh --profile minimal --gamedata <dir> # 最小子集 → <dir>/{names.json,img}
#   ./scripts/gen.sh --gamedata internal/gamedata/data --pb internal/pb \
#                    --pb-pkg github.com/whoisnian/rocom-capture/internal/pb   # rocom-capture 用法
# 选项:
#   --profile capture|minimal  生成哪一档(默认 capture;minimal 只出宠物名称/头像/血脉/炫彩/标记)
#   --out <dir>              生成物根(默认 build;各子目录默认在其下)
#   --gamedata <dir>         names.json + img/ 的目录(默认 <out>/gamedata)
#   --pbdesc <dir>           pcapdump 描述符目录(默认 <out>/pbdesc;minimal 档默认不出)
#   --pb <dir> --pb-pkg <p>  protoc 生成 Go 包到 <dir>,import 路径 <p>(默认不出)
#   --parsed <dir>           解包根(默认 $ROCOM_PARSED 或 ~/Downloads/rocom/parsed)
#   --no-unpack              不跑 unpack.sh(解包目录已是最新时省几秒)
#   --force                  图片全部重编(默认跳过已存在,见 docs/data.md 的 webp 漂移说明)
# 其余 unpack 参数(--paks/--aes/…)不透传:要改就单独跑 unpack.sh。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"

profile=capture
out=build
gamedata=""
pbdesc=""
pb=""
pb_pkg=""
parsed="${ROCOM_PARSED:-$HOME/Downloads/rocom/parsed}"
do_unpack=1
force=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile) profile="$2"; shift 2 ;;
        --out) out="$2"; shift 2 ;;
        --gamedata) gamedata="$2"; shift 2 ;;
        --pbdesc) pbdesc="$2"; shift 2 ;;
        --pb) pb="$2"; shift 2 ;;
        --pb-pkg) pb_pkg="$2"; shift 2 ;;
        --parsed) parsed="$2"; shift 2 ;;
        --no-unpack) do_unpack=0; shift ;;
        --force) force=(--force); shift ;;
        -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "未知参数: $1(--help 看用法)" >&2; exit 1 ;;
    esac
done
case "$profile" in capture|minimal) ;; *) echo "--profile 只能是 capture 或 minimal" >&2; exit 1 ;; esac
[[ -z "$gamedata" ]] && gamedata="$out/gamedata"
[[ -z "$pbdesc" && "$profile" == capture ]] && pbdesc="$out/pbdesc"
[[ -n "$pb" && -z "$pb_pkg" ]] && { echo "--pb 需要同时给 --pb-pkg <import 路径>" >&2; exit 1; }

export ROCOM_PARSED="$parsed"
export ROCOM_PROFILE="$profile"
export ROCOM_GAMEDATA_OUT="$gamedata"
[[ -n "$pbdesc" ]] && export ROCOM_PBDESC_OUT="$pbdesc"
[[ -n "$pb" ]] && export ROCOM_PB_OUT="$pb" ROCOM_PB_PKG="$pb_pkg"

py() { uv run --project "$REPO" python "$SCRIPT_DIR/$1" "${@:2}"; }

if [[ $do_unpack -eq 1 ]]; then
    echo "==> unpack(增量)"
    "$SCRIPT_DIR/unpack.sh" --out "$parsed"
fi
echo "==> gen_gamedata($profile)→ $gamedata/names.json"
py gen_gamedata.py
echo "==> gen_images → $gamedata/img"
py gen_images.py "${force[@]}"
echo "==> gen_icons → $gamedata/img"
py gen_icons.py "${force[@]}"
if [[ "$profile" == capture ]]; then
    echo "==> gen_bigmap → $gamedata/img/bigmap"
    py gen_bigmap.py "${force[@]}"
fi
if [[ -n "$pbdesc" ]]; then
    echo "==> gen_pbdesc → $pbdesc"
    py gen_pbdesc.py
fi
if [[ -n "$pb" ]]; then
    echo "==> gen_proto → $pb($pb_pkg)"
    py gen_proto.py
fi
echo "完成"
