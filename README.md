# rocom-parse

《洛克王国:世界》的解包与抓包分析工具箱,是 rocom-capture 的数据源与协议层:

- **解包**:`scripts/unpack.sh` 用 CUE4Parse 把游戏 pak 全量导出成 json/png/lua/bin
  (增量、并行,C# 实现在 `scripts/unpack/`),并自动解码 RocoBinData `.bytes` → `.json`、
  反编译 `.luac` → `.lua`。
- **生成**:`scripts/gen.sh` 从解包目录产出消费方要的一切——名称表 `names.json`、图标 webp、
  宠物消息的 Go 结构体、pcapdump 的描述符。**生成物不进仓库**,消费方构建时生成到自己的目录。
- **抓包分析**:`scripts/capture.sh` 在网关上录 pcap;`cmd/pcapdump` 回放并解密,输出结构化文本
  (opcode 概览 / 精确解码转储 / 宠物编号扫描)。
- **Go 包**:`gcp`(tsf4g/GCP 分帧、会话密钥、AES 解密)、`capture`(TCP 重组 + pcap 回放)、
  `pbdesc`(opcode → 消息类型的运行时反射),`github.com/whoisnian/rocom-parse` 供 rocom-capture import。

> 只服务于作者本人的玩具项目:只考虑自己的本地环境,凡是与此无关的事一律不做。
> 人工输出只有提示词,代码与文档均为 AI 生成;建议把 `docs/` 喂给 AI 做参考。

## 依赖

- dotnet SDK 10+(Arch: `pacman -S dotnet-sdk`)与 CUE4Parse 克隆(默认 `~/Git/CUE4Parse`,
  环境变量 `CUE4PARSE_DIR` 覆盖):要 `whoisnian/CUE4Parse` 的 **`rocom` 分支**,上游主线虽已
  支持当前版本的 pak,但仍缺若干修复,见 [docs/reference.md](docs/reference.md)。
- [uv](https://docs.astral.sh/uv/)(Python 脚本依赖,项目内 `.venv`,勿用系统 pip)。
- Go 1.26+、protoc + protoc-gen-go(`gen_proto.py`)。
- 可选:unluac(`.luac` 反编译)、tcpdump(`capture.sh`)。

## 用法

```bash
# 1. 游戏目录原样复制 pak(Windows 客户端 <安装目录>\Win64\NRC\Content\Paks;也可直接给安卓 .apk)
rsync -a --delete <游戏Paks目录>/ ~/Downloads/rocom/Paks/

# 2. 解包 + 生成(增量;默认全量档,产物在 ./build/)
./scripts/gen.sh
#    只解包:./scripts/unpack.sh [--list [子串]] [--filter <前缀>] [--no-exclude] [--force] …
#    消费方用法(rocom-capture 的 Makefile 就是这么调的):
./scripts/gen.sh --gamedata <repo>/internal/gamedata/data \
                 --pb <repo>/internal/pb --pb-pkg github.com/whoisnian/rocom-capture/internal/pb
./scripts/gen.sh --profile minimal --gamedata <dir>   # 只要宠物名称/头像/血脉/炫彩/标记的最小子集

# 3. 抓包分析
sudo ./scripts/capture.sh                       # 网关上录 pcap → ./pcap/
go run ./cmd/pcapdump -pcap pcap/*.pcap00        # opcode 概览
go run ./cmd/pcapdump -pcap x.pcap00 -op 0x1888,FREE -hex   # 转储
go run ./cmd/pcapdump -pcap x.pcap00 -gid 20508  # 宠物编号扫描
```

**解包后先核对开头的「挂载 N 个包」等于 `ls ~/Downloads/rocom/Paks/*.pak | wc -l`**:
解不开的包只打一行告警就整包跳过,退出码仍是 0,看着像「增量无变化」。

更新游戏版本:重新 rsync pak(`--delete`,残留的旧补丁包会反压新包)、重跑 `gen.sh`,
再按 [docs/data.md](docs/data.md) 末尾的清单排查字段剥离。

## 文档

- [数据来源与解析](docs/data.md) — 解包目录结构、Bin 配置/描述符、各 gen_* 的产物与坑
- [协议](docs/protocol.md) — GCP 字节布局、密钥、TCP 重组、pcapdump
- [宠物音频](docs/audio.md) — bnk/wem 与宠物的关联链路
- [参考资料](docs/reference.md) — CUE4Parse 分支、消费方、同类项目
