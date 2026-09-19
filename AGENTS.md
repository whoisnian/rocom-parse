# AGENTS.md

## 项目概述

`rocom-parse`:《洛克王国:世界》(进程 `com.tencent.nrc`)的解包 + 生成 + 抓包分析工具箱,
是 rocom-capture 的数据源与协议层。**本仓库不含任何解包数据或生成物**。
面向使用者的说明见 [README.md](README.md);设计细节见 `docs/`:
[数据来源与解析](docs/data.md)、[进化链](docs/petindex.md)、[协议](docs/protocol.md)、[宠物音频](docs/audio.md)、[参考资料](docs/reference.md)。

## 数据流

1. pak 原样复制到 `~/Downloads/rocom/Paks/`(或安卓 .apk)。
2. `scripts/unpack.sh` 用 CUE4Parse 全量解包到 `~/Downloads/rocom/parsed/`(`ROCOM_PARSED` 覆盖),
   按虚拟路径镜像:uasset/umap → 属性 json(纹理另出 png),其余原样字节。并行、增量(按来源 pak
   mtime),`--filter`/`--list`/`--no-exclude`(默认排除三维美术/视频/音频等)。C# 实现在
   `scripts/unpack/`,依赖 dotnet-sdk 与 CUE4Parse 克隆(默认 `~/Git/CUE4Parse`,须是 `whoisnian/CUE4Parse`
   的 `rocom` 分支;unpack.sh 会检查)。后置步骤:`.bytes` → 紧邻 `.json`(`bin2json.py`)、
   `.luac` → `.lua`(`decompile_luac.sh`,需 unluac)。
3. `scripts/gen.sh` 跑全部 `gen_*.py`:`gen_gamedata`(names.json)、`gen_images`/`gen_icons`/`gen_bigmap`
   (webp)、`gen_pbdesc`(pcapdump 描述符)、`gen_proto`(Go 结构体,给了 `--pb` 才出)、`petindex`
   (宠物链清单,给了 `--chains` 才出)。输出目录与档位(`--profile capture|minimal|chains`)的约定集中在
   `scripts/outdirs.py`,默认落 `build/`(gitignore)。
   进化链(包/组)只在 `scripts/petindex.py` 算一次,三个消费方(rocom-capture/agent/pets)同一口径,
   见 [docs/petindex.md](docs/petindex.md);改了规则先跑 `petindex.py --check`。

## 约定

- Go:`go build ./...`;`gcp`/`capture`/`pbdesc` 是给 rocom-capture import 的公开包,改 API 要同步那边。
  `capture` 与 `cmd/pcapdump` 保持纯 Go(实时 afpacket 源在 rocom-capture)。
- pcapdump:`go run ./cmd/pcapdump -pcap <文件…>`;无参=opcode 概览,`-op` 转储(精确解码,`-wire`
  退回 wire 级,`-msg` 强制类型),`-gid` 扫描;描述符从 `build/pbdesc` 加载(`-data` 覆盖),先跑 gen.sh。
- Python 脚本依赖用 uv 管理(项目内 `.venv`),勿用系统 pip;pillow 版本钉死以稳住 libwebp 字节。
- webp 生成默认「跳过已存在」:重编噪声与真变化要用 alpha 感知像素对比区分(见 docs/data.md);
  消费方要拿到真变化,删掉对应产物再跑,或整体 `--force` 重编并接受全量 diff。
- 数据来源均为自行解包提取,不依赖外部数据仓库。改生成逻辑改脚本,生成物从不手改。
- 更新游戏版本后必查:各生成脚本的 `!!` 告警、消费方 `go test`、上一版 `names.json` 逐键比条数并逐值 diff
  (游戏逐版本剥离策划字段,症状是零报错、某维度悄悄变空)。
