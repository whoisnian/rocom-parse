# 参考资料

与本项目相关的工具与开源项目(数据来源本身见 [data.md](data.md):
原始 pak → `~/Downloads/rocom/Paks/`,解包产物 → `~/Downloads/rocom/parsed/`)。

## 解包

| 项目 | 说明 |
| --- | --- |
| [CUE4Parse](https://github.com/FabianFG/CUE4Parse) | 上游解析引擎,内置 `GAME_RocoKingdomWorld` 游戏支持(自定义 AES 变体/Bin/luac,无需 usmap);其 `FRocoBinData.cs` 也是 `scripts/bin2json.py` 解 `.bytes` 配置的算法参照 |
| [whoisnian/CUE4Parse](https://github.com/whoisnian/CUE4Parse) `rocom` 分支 | **`scripts/unpack` 实际构建用的克隆**(`CUE4PARSE_DIR`,默认 `~/Git/CUE4Parse`)。上游 PR [#430](https://github.com/FabianFG/CUE4Parse/pull/430)(LukeFZ `nrc`:ver12 策略解密、MLE 算法、`26 4d 8b 5e` 文件容器、`\x1bMLE` luac 容器)与 [#434](https://github.com/FabianFG/CUE4Parse/pull/434)(压缩块整块解密并截到本块长度,缺则多块 MLE 条目如 `all.pb`/`proto.non` 解压失败;原为本分支 commit,2026-09-15 由上游等价实现覆盖后丢弃)已合入主线,但主线仍解不全,该分支 = 上游 master + 自有 commit:策略位只在 ver12 拆(缺则 ver11 pak 中 ≥1024 块的条目损坏)、glTF 无顶点色默认白、RKW 标量参数 Align(4)、RKW cooked 材质资源解出 LODUsed/DynamicSwitchId(后三条是 rocom-pets 导出器要的;本仓库不开 `ReadShaderMaps` 且默认排除 ArtRes,解包产物不受影响)。原有的 `FLua54Reader` LUAC_NUM 修复已由上游 lua writer 重写覆盖,rebase 时丢弃。unpack.sh 以 `FPakInfo.HasEncryptionStrategy` 识别该分支;修复合入上游主线后换回即可。新克隆要编 ACL 原生库:`git submodule update --init --recursive CUE4Parse-Natives/ACL/external/acl && cd CUE4Parse-Natives && cmake -B builddir -DCMAKE_BUILD_TYPE=RelWithDebInfo . && cmake --build builddir` |
| [FModel](https://github.com/4sval/FModel) | Windows GUI 解包器,手动导出备用路径,可与 `scripts/unpack.sh` 互为校验(该游戏条目 UeVersion=68812827 即 `GAME_RocoKingdomWorld`) |
| [unluac](https://github.com/HansWessels/unluac) | `.luac` → `.lua` 反编译(`scripts/decompile_luac.sh`,AUR: unluac) |

## 协议与同类项目

| 项目 | 说明 |
| --- | --- |
| [lsj9383/blog](https://github.com/lsj9383/blog) | tsf4g 通信协议说明 |
| [h3110w0r1d-y/rocom-helper](https://github.com/h3110w0r1d-y/rocom-helper) | 闭源洛克王国世界助手 |
| [yuzeis/Roco-Kingdom-Protocol-Parser](https://github.com/yuzeis/Roco-Kingdom-Protocol-Parser) | 开源洛克王国协议解析器,简称 RKPP |

## 消费方(本仓库的生成物与 Go 包供它们用)

| 项目 | 说明 |
| --- | --- |
| [rocom-capture](https://github.com/whoisnian/rocom-capture) | 网关被动抓包 + 宠物统计网页。构建时调 `scripts/gen.sh` 生成 gamedata / pb;import 本仓库的 `gcp`、`capture` 包 |
| [rocom-pets](https://github.com/whoisnian/rocom-pets) | 桌宠:宠物模型/动画/材质还原(Rust 客户端 + 捆绑的 C# 导出器)。不用本仓库的脚本,只共用同一个 CUE4Parse 克隆 |
