#!/usr/bin/env bash
#
# unpack.sh — 在 Linux 上从游戏 pak 全量解包(见 docs/data.md)
#
# 封装 scripts/unpack/(C#,基于 CUE4Parse 的 GAME_RocoKingdomWorld 支持):
# 从 ~/Downloads/rocom/Paks/(游戏目录原样复制的 pak)全量导出到 ~/Downloads/rocom/parsed/,
# 按虚拟路径镜像:uasset/umap → json(纹理另出 png),其余(.bytes/.non/.pb/.lua 等)原样字节。
# 生成脚本(gen_proto/gen_gamedata/gen_images/gen_icons/gen_bigmap)直接读 parsed/。
# 并行解码,增量跳过产物不比来源 pak 旧的项(补丁包原地改的同名文件会自动重导);
# 默认排除纯客户端运行时资源(三维美术/视频/音频/着色器等,
# 约占全量 74G/80G,清单见 --help),--exclude 追加、--no-exclude 恢复真·全量。
#
# 导出后自动跑两个后置步骤(增量,--no-post 跳过;缺依赖时提示后继续):
#   1. 全树 .bytes → 紧邻 .json(scripts/bin2json.py,需 uv;既供查数据也是 gen_* 输入);
#   2. .luac → .lua 反编译(scripts/decompile_luac.sh,需 unluac)。--list/--help 与导出失败(rc=1)时不跑。
#
# 用法:
#   ./scripts/unpack.sh                          # 默认 Paks → parsed 增量导出(含默认排除+后置步骤)
#   ./scripts/unpack.sh --list [substr]          # 只列清单不导出
#   ./scripts/unpack.sh --filter NRC/Content/ScriptC   # 只导指定前缀
#   ./scripts/unpack.sh --no-post                # 只导出,不跑 Bin 解码/luac 反编译
#   其余参数(--paks/--out/--aes/-j/--exclude/--force/...)见 --help,原样透传给 C# 工具。
#
# AES 主密钥默认用下方 DEFAULT_AES(与 Windows FModel AppSettings.json → AesKeys 同一把,
# 换密钥的版本传 --aes 覆盖)。
# 依赖:dotnet SDK 10+(pacman -S dotnet-sdk);CUE4Parse 克隆(默认 ~/Git/CUE4Parse,
# 环境变量 CUE4PARSE_DIR 覆盖;当前游戏版本的 pak 需带 ver12 解密支持的克隆,见 docs/data.md);
# 首次运行会往 ~/.cache/nrc-unpack 下载 oodle/zlib-ng 原生库。
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ="$SCRIPT_DIR/unpack"

command -v dotnet >/dev/null 2>&1 || {
    echo "错误: 未找到 dotnet,请先安装 .NET SDK 10+(Arch: pacman -S dotnet-sdk)" >&2
    exit 1
}

CUE4PARSE_DIR="${CUE4PARSE_DIR:-$HOME/Git/CUE4Parse}"
[[ -f "$CUE4PARSE_DIR/CUE4Parse/CUE4Parse.csproj" ]] || {
    echo "错误: 未找到 CUE4Parse 仓库: $CUE4PARSE_DIR" >&2
    echo "  克隆一份,或设环境变量 CUE4PARSE_DIR 指向已有克隆" >&2
    exit 1
}
# 当前游戏版本(ver12 pak)的解密支持还没进上游主线(解不开时只打一行告警就整包跳过,
# 不报错),故这里认一个带该支持的克隆才有的文件,免得导出「零失败但零内容」:
# whoisnian/CUE4Parse 的 rocom 分支(= 上游 + PR #430 + 自有修复,见 docs/reference.md)。
# 合入上游主线后可去掉本段。
[[ -f "$CUE4PARSE_DIR/CUE4Parse/GameTypes/Tencent/RocoKingdomWorld/Encryption/NRCPakFileReader.cs" ]] || {
    echo "错误: $CUE4PARSE_DIR 解不开当前版本的 pak,需要带 ver12 解密支持的 CUE4Parse 克隆(rocom 分支)" >&2
    exit 1
}
export CUE4PARSE_DIR

# 解析:剥离本脚本私有的 --no-post(C# 工具不识别);记录 --out、是否 --aes、是否只列不导。
DEFAULT_AES="0x34254D23E47299B3B7F6C4CFDE9BD0688703446D9D8F37B2EBDDDE5B06ED5ADF"
has_aes=0
run_post=1
skip_post_mode=0   # --list/--help 只查看,不跑后置步骤
OUT_DIR="$HOME/Downloads/rocom/parsed"   # 与 C# 工具默认一致
dll_args=()
prev=""
for a in "$@"; do
    case "$a" in
        --no-post) run_post=0; prev=""; continue ;;
        --aes|--aes-file) has_aes=1 ;;
        --list|-h|--help) skip_post_mode=1 ;;
    esac
    [[ "$prev" == "--out" ]] && OUT_DIR="$a"
    dll_args+=("$a")
    prev="$a"
done
extra=()
[[ $has_aes -eq 0 ]] && extra=(--aes "$DEFAULT_AES")

# -c Release:纹理解码是 CPU 密集,Debug 构建慢一倍以上
# 先静默构建(CUE4Parse 自身有几百个 CS86xx 警告,只留错误),再跑产物
dotnet build "$PROJ" -c Release --nologo -v q -clp:ErrorsOnly

# 只列/查看,或明确 --no-post:直接跑并退出(--list/--help 无后置意义)
if [[ $skip_post_mode -eq 1 || $run_post -eq 0 ]]; then
    exec dotnet "$PROJ/bin/Release/net10.0/NrcUnpack.dll" "${extra[@]}" "${dll_args[@]}"
fi

# 导出(rc: 0 全成功 / 2 有个别失败项,均继续后置;1 参数或挂载错误则中止)
set +e
dotnet "$PROJ/bin/Release/net10.0/NrcUnpack.dll" "${extra[@]}" "${dll_args[@]}"
rc=$?
set -e
[[ $rc -eq 1 ]] && exit $rc

# ── 后置步骤(增量,缺依赖时提示后继续)──────────────────────────────
REPO="$(dirname "$SCRIPT_DIR")"

# 1. 全树 RocoBinData .bytes → 紧邻 .json(供 grep/jq 查数据,也是 gen_* 的输入,增量秒级)
if command -v uv >/dev/null 2>&1; then
    echo "==> 解码 .bytes 为 JSON..."
    uv run --project "$REPO" python "$SCRIPT_DIR/bin2json.py" "$OUT_DIR" || echo "  (bin2json 失败,跳过)"
else
    echo "==> 跳过 .bytes→JSON:未找到 uv" >&2
fi

# 2. .luac → .lua 反编译(增量;缺 unluac 时脚本自行提示并退出 0)
echo "==> 反编译 luac..."
"$SCRIPT_DIR/decompile_luac.sh" "$OUT_DIR" || echo "  (decompile_luac 失败,跳过)"

exit $rc
