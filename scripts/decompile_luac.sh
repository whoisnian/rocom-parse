#!/usr/bin/env bash
#
# decompile_luac.sh — 把解包出的 Lua 5.4 字节码(.luac)反编译为可读源码(.lua)
#
# scripts/unpack.sh 解出的 .luac 是编译后的标准 Lua 5.4 字节码(见 docs/data.md),
# 用已安装的 unluac(AUR: unluac,/usr/bin/unluac → java -jar)反编译,输出 <name>.lua
# 与 .luac 同名同目录。并行(nproc)、增量(.lua 比 .luac 新则跳过);--force 全部重来。
# 缺 unluac 时打印提示后正常退出(0),不阻断上游 unpack.sh。
#
# 用法:
#   ./scripts/decompile_luac.sh                 # 默认根 ~/Downloads/rocom/parsed(ROCOM_PARSED 覆盖)
#   ./scripts/decompile_luac.sh <解包根目录>    # 或指定根(递归找 .luac)
#   ./scripts/decompile_luac.sh --force         # 忽略增量,全部重反编译
#
set -euo pipefail

FORCE=0
ROOT=""
TIMEOUT="${LUAC_TIMEOUT:-60}"   # 单文件反编译上限秒;unluac 对个别字节码会死循环,超时即弃
for a in "$@"; do
    case "$a" in
        --force) FORCE=1 ;;
        *) ROOT="$a" ;;
    esac
done
ROOT="${ROOT:-${ROCOM_PARSED:-$HOME/Downloads/rocom/parsed}}"

[[ -d "$ROOT" ]] || { echo "源目录不存在: $ROOT(可传解包根或设 ROCOM_PARSED)" >&2; exit 1; }
command -v unluac >/dev/null 2>&1 || {
    echo "未找到 unluac(AUR: unluac),跳过 luac 反编译" >&2
    exit 0
}

export FORCE TIMEOUT

# 单文件反编译:写临时文件成功再原子改名,失败/空输出不留残缺 .lua。
# timeout 兜住 unluac 对个别字节码的死循环(否则并行池被挂死进程占满、整体卡住)。
# 输出 ok/skip/fail/timeout 各一行(供父进程计数),失败路径另打到 stderr。
work() {
    local f="$1" out="${1%.luac}.lua" bad="${1%.luac}.lua.nodecomp"
    # 增量跳过:已成功(.lua 更新)或已知搞不定(.nodecomp 标记更新)。--force 忽略两者。
    # 标记让 unluac 死循环/报错的极少数文件不在每次增量重跑时白耗(尤以 45s 超时者)。
    if [[ $FORCE -eq 0 && -f "$out" && "$out" -nt "$f" ]]; then echo skip; return; fi
    if [[ $FORCE -eq 0 && -f "$bad" && "$bad" -nt "$f" ]]; then echo skip; return; fi
    local tmp rc
    tmp=$(mktemp "$out.XXXXXX")
    timeout -k 5 "$TIMEOUT" unluac "$f" >"$tmp" 2>/dev/null
    rc=$?
    # rc=0 即成功:空输出是合法空模块(源仅注释/空,字节码只有 _ENV),照写空 .lua 保证增量幂等。
    # rc!=0 丢弃可能的半截输出(unluac 报错时会吐部分代码,截断反而误导),打个 .nodecomp 标记。
    if [[ $rc -eq 0 ]]; then
        mv "$tmp" "$out"
        echo ok
    else
        rm -f "$tmp"
        : > "$bad"
        if [[ $rc -eq 124 || $rc -eq 137 ]]; then
            echo "  反编译超时(${TIMEOUT}s): $f" >&2
            echo timeout
        else
            echo "  反编译失败: $f" >&2
            echo fail
        fi
    fi
}
export -f work

echo "反编译 $ROOT 下 .luac → .lua(unluac,并行 $(nproc))..."
find "$ROOT" -name '*.luac' -print0 \
    | xargs -0 -r -P "$(nproc)" -I{} bash -c 'work "$@"' _ {} \
    | sort | uniq -c \
    | awk '{c[$2]=$1} END{printf "-> 完成: ok %d,跳过 %d,失败 %d,超时 %d\n", c["ok"], c["skip"], c["fail"], c["timeout"]}'
