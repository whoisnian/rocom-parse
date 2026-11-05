# 参考资料

与本项目相关的工具与开源项目(数据来源本身见 [data.md](data.md):
原始 pak → `~/Downloads/rocom/Paks/`,解包产物 → `~/Downloads/rocom/parsed/`)。

## 解包

| 项目 | 说明 |
| --- | --- |
| [CUE4Parse](https://github.com/FabianFG/CUE4Parse) | 上游解析引擎,内置 `GAME_RocoKingdomWorld` 游戏支持(自定义 AES 变体、ver12 策略解密(AES/SM4)与 MLE 容器、Bin/luac,无需 usmap);其 `FRocoBinData.cs` 也是 `scripts/bin2json.py` 解 `.bytes` 配置的算法参照 |
| [whoisnian/CUE4Parse](https://github.com/whoisnian/CUE4Parse) `rocom` 分支 | **`scripts/unpack` 实际构建用的克隆**(`CUE4PARSE_DIR`,默认 `~/Git/CUE4Parse`)。上游主线仍解不全,该分支 = 上游 master + 自有 commit:ver12 pak 条目的加密策略(位编码条目只在 ver12 拆策略位,缺则 ver11 pak 中 ≥1024 块的条目损坏;非编码条目(≥1024 块)从 Flags 高 6 位取策略,缺则当前版本两个大 ubulk 解压失败)、RKW 材质实例只在读过内联 shader map 后才读 DynamicSwitchParameters(本仓库不开 `ReadShaderMaps`,缺则 `--no-exclude` 导出 ArtRes 时绝大多数 MaterialInstanceConstant 报错)、RKW cooked 材质资源布局(标量参数 Align(4)、解出 LODUsed/DynamicSwitchId)、ACL 默认旋转子轨取单位四元数而非绑定姿势(后两条是 rocom-pets 导出器要的;本仓库不开 `ReadShaderMaps` 且默认排除 ArtRes(含动画),解包产物不受影响)。unpack.sh 以 `FPakInfo.HasEncryptionStrategy` 与 `FPakEntry` 从 Flags 取策略的代码识别该分支;修复合入上游主线后换回即可。新克隆要编 ACL 原生库:`git submodule update --init --recursive CUE4Parse-Natives/ACL/external/acl && cd CUE4Parse-Natives && cmake -B builddir -DCMAKE_BUILD_TYPE=RelWithDebInfo . && cmake --build builddir` |
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
