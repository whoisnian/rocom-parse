# 数据来源与解析

数据流程分三级,原始解包数据与生成物**都不进仓库**(本仓库只有脚本与文档):

1. **原始 pak**:从游戏目录原样复制到 `~/Downloads/rocom/Paks/`
   (Windows 客户端 `<安装目录>\Win64\NRC\Content\Paks`;安卓 .apk 亦可直接喂给解包器)。
2. **全量解包**:`scripts/unpack.sh` 用 CUE4Parse 把 pak 尽可能全量导出到
   `~/Downloads/rocom/parsed/`(json/png/lua/bin 等,详见下)。
3. **生成物**:`scripts/gen.sh`(逐个脚本是 `scripts/gen_*.py`)直接读 `parsed/`,产出
   `names.json` 与 `img/` 下的 webp(游戏数据)、`*.pb.go`(宠物消息的 Go 结构体)、
   `pbdesc/`(pcapdump 的描述符)。默认落到本仓库的 `build/`(gitignore);
   消费方(如 rocom-capture)的 Makefile 把它们生成到自己 `go:embed` 的目录
   (同样不提交),`go build` 前先跑一遍即可。输出目录/档位的约定见 `scripts/outdirs.py`
   与 `gen.sh --help`:`--profile capture` 全量,`--profile minimal` 只出宠物名称/头像/血脉/炫彩/标记。

生成脚本用到的两类源(均在解包目录内,`ROCOM_PARSED` 环境变量可覆盖解包根):

- **游戏二进制配置 `NRC/Content/ScriptC/Data/Bin/`**:提供**中文名称表**。游戏自有的
  `.bytes`(数据)+ `.non`(schema)+ `BinLocalize/dev_CN`(本地化),由 `scripts/bin2json.py`
  解为紧邻的 `.json`(unpack.sh 已自动解码),生成脚本读该 JSON。
- **游戏描述符 `NRC/Content/ScriptC/Data/PB/all.pb`**:游戏自带的 protobuf 描述符
  (`FileDescriptorSet`,即运行时 `pb.loadufsfile` 加载的同一份),提供生成的 Go 结构体的
  **字段号/类型**与 **opcode/枚举**。含字段号,可直接喂给 protoc 生成 Go,无需 .proto 文本。

字段号/枚举是**追加式**的(新版本只加不改号),故几乎无需跟版本更新;名称表随游戏内容变动。
要更新到新版本游戏:重新复制 pak、重跑 `scripts/gen.sh`(内含增量 unpack)。
行 id 同样跨版本稳定(实测大版本更新后星星刷新行 id 原样不动)。

> **全量解包(`scripts/unpack.sh`)**:从游戏 pak(目录或安卓 .apk)按虚拟路径镜像导出到
> `~/Downloads/rocom/parsed/`(顶层即挂载根 `NRC/Content/...`):`.uasset`/`.umap` 导出为
> 同路径属性 **.json**(含 PaperSprite UV 等全部导出属性),内含纹理的包另出同路径 **.png**
> (Texture2D 解码);其余文件(`.bytes`/`.non`/`.pb`/`.lua`/`.luac`/`.ini` 等)**原样字节**;
> `.uexp`/`.ubulk` 随包体读取不单独落盘。`Parallel.ForEach` 并行解码,**增量**跳过产物存在
> 且不比其来源 pak 旧的项(小版本补丁包 `_N_P` 多是原地改同名文件,只判存在与否会把这些改动
> 全部静默跳过、解包停在旧版本,故按 mtime 比对),`--list` 预览、`--filter` 按前缀选导、
> `--force` 全部重导。**默认排除**纯客户端运行时
> 资源(ArtRes 三维美术、Movies 视频、WwiseAudio 音频、AI 行为树、PVS/着色器/PSO 缓存、Engine;
> 约占全量 74G/80G,下游脚本零引用,清单见 `--help`),`--exclude <前缀>` 追加排除、
> `--no-exclude` 恢复真·全量。RenderTarget/视频纹理无像素数据,只出属性 json 不出 png
> (降级为记录、json 照写)。
>
> 导出后自动跑两个**后置步骤**(增量,`--no-post` 跳过;`--list`/`--help`/导出致命错时不跑):
> ①全树 RocoBinData `.bytes` → 紧邻 `.json`(`scripts/bin2json.py`,需 uv);②`.luac` → `.lua` 反编译
> (`scripts/decompile_luac.sh`,需 unluac)。`.luac` 本是标准 Lua 5.4 字节码(编译产物),
> unluac 反编译回可读源码(绝大多数成功);单文件 `timeout`(默认 60s,`LUAC_TIMEOUT` 覆盖)
> 兜住 unluac 对个别字节码的死循环,失败/超时打 `.lua.nodecomp` 标记、增量重跑跳过不再白耗;
> 空模块(源仅注释/空)合法解出空 `.lua`。
> C# 实现在 `scripts/unpack/`,基于 CUE4Parse 的 `GAME_RocoKingdomWorld` 支持(自定义
> AES 字节置换变体、Bin/luac 专属处理,无需 usmap)。当前游戏版本 pak(ver12)的解密已随上游
> PR [#430](https://github.com/FabianFG/CUE4Parse/pull/430)(LukeFZ `nrc`)进主线,多块压缩加密条目
> (`all.pb`、`proto.non`、UI 图集等)的解压也已随 [#434](https://github.com/FabianFG/CUE4Parse/pull/434)
> 修好,但**主线仍解不全**:旧版 ver11 pak 的大条目块数被截。
> 要用自己 fork 的 `whoisnian/CUE4Parse` **`rocom` 分支** = 上游 master + 自有修复(见 docs/reference.md;
> 默认位置 `~/Git/CUE4Parse`,`CUE4PARSE_DIR` 覆盖;unpack.sh 会检查)。修复合入上游主线后换回主线即可。
> 依赖 dotnet-sdk 10+;首次运行自动下载 oodle/zlib-ng 到
> `~/.cache/nrc-unpack`。AES 主密钥默认值已内置在 `unpack.sh`(`DEFAULT_AES`,换密钥的版本用
> `--aes <hex>`/`@文件` 覆盖;与 Windows FModel `AppSettings.json → AesKeys` 同一把,该游戏
> 条目的 UeVersion=68812827 即 `GAME_RocoKingdomWorld`,usmap endpoint 未启用,口径一致)。

> **解包后先核对开头的「挂载 N 个包」是否等于 `ls ~/Downloads/rocom/Paks/*.pak | wc -l`**:
> 解包器解不开的包只打一行告警就整包跳过,退出码仍是 0、结尾报「共 0 项」,看着像「增量无变化」,
> 实则新版本一个文件都没导出。

> **发布数据里没有策划专用字段**(editor_name、max_num、npc_pendant_id、`WORLD_MAP_BLOCK_CONF.is_world_map`、
> `MEDAL_TASK_CONF` 的判定字段等),解析只可依赖仍随包发布的字段与表:石像奖励行按刷新区域顶点数排除、
> 带星石像按 NPC_PENDANT_CONF 判定;星点→区域归属走 `CAMP_CONF.area_id` 管辖区外键链;大世界图按
> 客户端判据 `BigMapUtils.IsHomeScene`(`SCENE_RES_CONF.scene_id != 301`);百分位奖牌按 task id 固定维度、
> 窗口从 desc 文本读。**游戏更新还会继续剥离或改名字段**,症状都是「脚本零报错、某个维度悄悄变空或变错」
> (改名比删更阴:`.get(旧名) or 0` 静默取 0)。
> **更新后必查**:各生成脚本的 `!!` 告警、消费方 `go test ./...`、拿上一版 `names.json` 逐键比条数
> **并逐值 diff**(只比条数会漏掉布尔翻转)。**字段没了先别急着硬编码**:先在 schema `.non` 的字段列表里
> 找有没有改名的同义字段,再去反编译的客户端 `.lua` 看它自己怎么判。

## 1. 名称表数据来源(解包目录 `ScriptC/Data/Bin/`)

Bin 目录下:

| 路径 | 内容 |
| --- | --- |
| `BinConf/*.non` | 表结构 schema(JSON,字段名/类型/偏移) |
| `BinDataCompressed/*.bytes` | 表数据(游戏自有压缩二进制) |
| `BinLocalize/dev_CN/*.bytes` | 本地化字符串(`ELocalizedString` 字段经此解析) |
| `BinDataCompressed/BinDataCompressed_ROW/*.bytes` | **国际服(ROW = Rest Of World)覆盖包**(当前 4 张 ACTIVITY 表),见下 |

`scripts/bin2json.py` 按 CUE4Parse 的 `FRocoBinData` 算法(自行实现,是全仓 `.bytes` 解码的
唯一实现)把全树 RocoBinData `.bytes` 解为紧邻的 `.json`:压缩/定长表 `{"RocoDataRows":{id:{...}}}`、
本地化 `{"LocalizationStrings":{...}}`(magic `0x53DF17BE` 识别,非此格式如 BigMap 的 `.bytes` 跳过)。
`gen_gamedata.py`/`gen_icons.py` 直接读 `BinDataCompressed/<表>.json`,不再自行解 `.bytes`。

> **`BinDataCompressed_ROW/`(国际服覆盖包)**:客户端 `DataConfigManagerNew:InitTableInfo` 按
> `RocoEnv.IS_INTERNATIONAL_ROW` 决定串表语言(国服固定 `dev_CN`,国际服跟设备语言),这批同名表
> 就是国际服那套内容。**schema 与基础表共用**(`BinConf/<名>.non`),行也按同样规则解——4 张里
> 3 张自带完整表尾/数据表/常量表,逐行「解析消耗字节数 == 数据表记的行长」全部自洽;
> 剩下的 `ACTIVITY_CONF` 只有数据段、没有表尾与常量表(残件),解不了,`bin2json.py` 单独计数
> 报「残件跳过」、不算失败。**但 ELocalizedString 解不出文本**:每张表的串 id 是各自表内
> 1..N 的稠密序号,配套串表没随国服包发布(实测该表用到 id 1..291,而 `dev_CN` 是国服基础表的
> 526 条、`zh_Hans` 是国际服**基础**表的 278 条,都对不上),故这些字段留**原始 id**,
> 不挂串表硬解——否则会解出「看着像话、其实是另一条」的文本。这几张表下游零引用,只作查数据用。
opcode/枚举不在 Bin 里,取自 `all.pb`(见第 2、3 节)。unpack.sh 导出后自动解码,也可手动
`uv run python scripts/bin2json.py` 重跑(增量,秒级);之后直接 grep/jq。

关键表：

- `MONSTER_CONF` + `PET_CONF` — 宠物种类名(`conf_id → name`)。
  常规宠物在 MONSTER_CONF，彩蛋/特殊宠物在 PET_CONF，两表 id 不重叠，合并取用。
- `AUDIO_NATURE_CONF` — 性格名(`nature_id → name`，内联 `EString`，无需本地化)
- `MEDAL_CONF` — 奖牌名(`ELocalizedString`)与描述
- `PET_TALENT_CONF` — 特长名(`speciality_id → name`)
- `PET_FILTER_CONF` — 系别/天分/标记的 `filter_enum_value → filter_desc`(中文);另含筛选图标引用(见 3 节末)
- `PET_BLOOD_CONF` — 血脉(24 条:18 属性系 + 首领/巨兽/黑魔法/异核/污染/奇异)的主图标 `icon` 引用(见 3 节末)
- `PET_LIKE_ELEMENT_CONF` — 蛋组(繁殖组)。`id`(1~15)即 `PETBASE_CONF.egg_group` 列表里的编号,
  `pet_like_reason` 对应 `all.pb` 的 `PetEggGroup` 枚举 `PEG_*`;`editor_name1` 为策划编辑器标签
  (「名称:描述」格式,官方 Bin 字段而非本地化 UI 串),取「:」后作蛋组描述保留。显示名不用其内定名,
  改用社区更流行的叫法(未发现/巨灵/两栖/昆虫/天空/动物/妖精/植物/拟人/软体/大地/魔力/海洋/龙/机械,
  硬编码于 `gen_gamedata.py` 的 `EGG_GROUP_NAMES`)。id 16+ 为繁殖组合标记,忽略。
- `PETBASE_CONF` + `MODEL_CONF` — 宠物图片引用(`JL_res` 全身图、`model_conf→icon` 头像;见 3 节末)
- `SCENE_CONF` + `SCENE_RES_CONF` + `WORLD_MAP_BLOCK_CONF` — 场景名与大地图投影(见 rocom-capture docs/map.md 1)
- `LAYERED_WORLD_MAP_CONF` + `AREA_FUNC_CONF` — 分层地图(洞穴/地下层)切片图与投影(见 rocom-capture docs/map.md 2)
- `WORLD_MAP_CONF` + `NPC_REFRESH_CONTENT_CONF` + `AREA_CONF` + `SCENE_OBJECT_CONF`
  — 大地图 POI(炼金釜/魔力之源/…)的图标与坐标(见 rocom-capture docs/map.md 3)。这几张是 Bin 里最大的
  (AREA_CONF 9.1M、NPC_REFRESH 2.3M),但坐标只能从它们来
  (`NPC_CONF` 2.0M 现已不被生成脚本读取,留作星星 NPC id/`min_map_disappear` 外键的查证依据)
- `NPC_PENDANT_CONF` — NPC 挂件(带星石像的判据与挂件星 npc,见 rocom-capture docs/map.md 3/4;行 id = 石像刷新行 id
  = pcap 里的 `pendant_cfg_id`)
- `WORLD_EXPLORING_STATISTIC_CONF` — 探索统计注册表:「眠枭之星」行的 npc 清单即服务器
  explore_infos 计数的那批 npc_id(九个,与 STAR_NPCS/star.go 的 starNpc 同一批);生成脚本
  据此做防锈校验,新版本增删星 npc 会报警(见 rocom-capture docs/map.md 3)
- `CAMP_CONF` — 营地表(行 id = 营地刷新点 id = explore_infos 的 belong_camp):
  `area_id` 外键给出区域管辖多边形,是星点→区域归属的权威来源(见 rocom-capture docs/map.md 4)
- opcode/系别/天分/标记的整数枚举取自 `all.pb`(`ZoneSvrCmd`/`SkillDamType` 等)

## 2. 描述符 → Go(`scripts/gen_proto.py`，数据源:all.pb)

`all.pb` 已是合法的 `FileDescriptorSet`(含字段号/类型)，直接喂给
`protoc --descriptor_set_in` 即可生成 Go,**无需 .proto 文本**。

只生成 `com_pet.proto` + `com_pet_team.proto`(大世界队伍)两个根的**依赖闭包**(由脚本从描述符
**动态求取并合并**,随 all.pb 版本而变,当前约 9 个文件:com_pet/com_base_types/com_battle_enum/
com_monster/com_pet_skill/com_season/rpc_options/xls_enum/com_pet_team),
用 `--go_opt=M...` 映射到单一 Go 包(import 路径由 `ROCOM_PB_PKG` 给,消费方指自己的 `internal/pb`)。
`all.pb` 不含 well-known 的 `descriptor.proto`(被 rpc_options 依赖),脚本用 protobuf 运行时
自带的描述符在内存里补进描述符集(见 `scripts/pbdesc.py`)。产物为 `$ROCOM_PB_OUT/*.pb.go`。

核心结构 `PetData`(`com_pet.proto`)字段对应展示项：

| 截图字段 | PetData 字段 |
| --- | --- |
| 编号 | `gid`(实例唯一 id) |
| 种类 | `conf_id` → PET_CONF.name |
| 昵称 | `name`(玩家命名) |
| 系别 | `skill_dam_type`(repeated SkillDamType) |
| 性格 | `nature` |
| 性别 | `gender`(1=♂,2=♀) |
| 等级 | `level` |
| 身高/体重 | `height`/100 米、`weight`/1000 千克 |
| 天分 | `talent_rank` → PetTalentRate |
| 奖牌 | `wear_medal_conf_id` → MEDAL_CONF |
| 特长 | `speciality_id` → PET_TALENT_CONF.name |
| 标记 | `partner_mark` |
| 声音 | `voice` |
| 捕捉时间 | `add_time`(unix 秒) |
| 六维 | `attribute_new_info`(最终面板值，按 AttributeType 1-6 取) |

## 2.1 描述符 → pcapdump 精确解码(`scripts/gen_pbdesc.py`)

gen_proto 生成的静态结构体只覆盖宠物相关那几个消息(线上解析路径要静态类型),调试新协议时够不着。
`gen_pbdesc.py` 另出一份**运行时反射用**的生成物到 `$ROCOM_PBDESC_OUT`(默认 `build/pbdesc`,
`pcapdump` 运行时从该目录加载,`-data` 指定):

- `opmsg.json`:opcode → 消息全名(1696 条)。映射表在客户端 `ProtoCMD.lua`
  (`[ProtoCMD.ZoneSvrCmd.X] = ".Next.Y"`),opcode 数值取 all.pb 的 `ZoneSvrCmd`/`ZoneSvrGmCmd`
  枚举,两边对得上才收(有 22 个消息名 lua 里有、描述符里还没有,跳过)。
- `opname.json`:opcode → `ZoneSvrCmd` 枚举名全集(1447 条),pcapdump 概览与 `-op` 名称匹配用。
- `proto.desc.gz`:裁剪过的 `FileDescriptorSet`(gzip 190KB)。只留从上述消息**字段可达**的
  消息与枚举(3244/4005 消息、189/1128 枚举),service/自定义 option 扩展全丢;
  被引用的嵌套枚举若其外层消息用不上,外层留个空壳撑住命名(否则解析报找不到类型)。

pcapdump 用它 + `dynamicpb` 解出带字段名/枚举名的树(`cmd/pcapdump/typed.go`)。消息在
`AppBody` 里的边界要试:头部 s2c 是 0、c2s 还剩 6 字节子头,尾部是 tsf4g 校验尾,
以 `"tsf4g"` 为锚在 `[起始 0..16] × [结束 tail-24..tail]` 里取「解出来没有未知字段 +
消费字节最多 + 回序列化长度一致」的候选。104 种 opcode 实测 103 种能精确解出,
唯一的例外 `0x013f ZONE_SCENE_HEARTBEAT_RESULT_NTY` 根本不是 protobuf(定长二进制结构),
自动退回通用 wire 级解码。

> 回序列化只比长度不比字节:Go 按字段**声明顺序**编码,服务端按**字段号**顺序,
> 本协议里两者常不一致,字节序列不同但长度必然相同。

## 3. 名称表 → JSON(`scripts/gen_gamedata.py`)

从上述表提取精简 `id → 中文名` 写入 `$ROCOM_GAMEDATA_OUT/names.json`,消费方
(rocom-capture 的 `internal/gamedata`)编译期 `embed` 加载。当前 37 个维度,按用途分五组:

| 组 | 键 | 详见 |
| --- | --- | --- |
| 宠物本体 | `species` `petbase` `nature` `nature_effect` `skill_dam_type` `talent_rate` `partner_mark` `partner_marks` `speciality` `medal` `size_medals` `blood_names` `egg_group` `glass_names` `glass_colors` `glass_particles` | rocom-capture docs |
| 图片索引 | `images` `image_base` `filter_icons` `blood_icons` `medal_icons` `static_icons` | 本文下两节 |
| 场景与地图 | `scenes` `scene_res` `scene_default_res` `maps` `layers` `zones` `poi_kinds` `pois` `npc_pets` `npc_bosses` | rocom-capture docs/map.md |
| 精灵蛋 | `egg_conf` `egg_items` `egg_types` `nest_furniture` | rocom-capture docs/eggs.md |
| 协议 | `opcodes` | 本文 §2 |

名称表由 `bin2json.py` 解出的 Bin JSON 得到;系别/天分/标记的整数值通过解析 `all.pb`
枚举(名→整数)再 join `PET_FILTER_CONF` 的(枚举名→中文)得到。种类合并 MONSTER_CONF+
PET_CONF，特长直接取 PET_TALENT_CONF，opcode 取自 `all.pb` 的 `ZoneSvrCmd` 全集
(枚举/opcode 均经 `scripts/pbdesc.py` 读描述符,与 `internal/pb` 同源),性别为硬编码。

### 宠物图片索引(`images` / `image_base`)

链路:`PetData.conf_id` → `MONSTER_CONF`/`PET_CONF` 行的 **`base_id`** → `PETBASE_CONF.id`(基础形态)
→ 全身图取 `PETBASE.JL_res`(`Pet1024/Pet256/<资源名>`),头像经 `PETBASE.model_conf` →
`MODEL_CONF.icon`/`big_icon`(`HeadIcon/BigHeadIcon256/<n>`)。**文件名不能用 id 拼**——461 个
形态的头像文件名不是自身 id(如 3242 用 3012),全身图是资源代号而非 id,故必须存表。

> 全身图文件名有**两套命名并存**:`JL_<拼音>`(如 `JL_emoding`)与
> `img_<系别>_<名><代>_<变体>_Res`(如 `img_Ill_QiuQiu1_001_Res`,`001` 普通 / `101` 异色)。
> 故 `images` **存原样完整文件名**、Go 侧只拼目录与扩展名,不做前缀增删。

`gen_gamedata.py` 输出两张:`images`(petbase_id → `{h,b,p,ps,…}` 文件名,1122 项)与
`image_base`(conf_id → petbase_id,仅 base≠自身者,约 2 万项;base==自身者 Go 侧回退直查)。
`gamedata.PetImage(confID, shiny)` 据此拼出相对路径(`HeadIcon/3001.webp` 等),挂到 `Pet.Image`,
前端拼到 `/img/` 下。未上线宠(如占位的圣草帝魔)无美术资源,`PetImage` 返回空,前端给占位图。
> 实际形态以 `PetData.base_conf_id`(当前 petbase)为准:`ToPet` 优先用它取名称/头像/图鉴/形态,
> 缺失才回退 `conf_id`(进化线一阶 base)——否则已进化宠物会显示成基础形态(详见进化形态一节)。

**异色(shiny)变体**:部分宠物有专属异色美术——头像 `MODEL_CONF.shiny_icon`/`big_shiny_icon`
(形如 `3010_1`)、全身图 `PETBASE.JL_shiny_res`/`JL_small_shiny_res`(形如 `JL_<拼音>_yise`
或新命名的 `..._101_Res`)。
`images` 仅在与普通版**不同**时额外存 `{sh,sb,sps}`(本版本 291/261/244 项;多数宠异色复用普通图)。
`PetImage(confID, true)` 在「索引有该字段**且**对应 webp 确已 embed」时才用异色图,否则回退普通——
故未导出异色 PNG 时异色宠仍显示普通美术,不会出现空图标。

图片本体(webp)由消费方 **embed 进二进制**:解包目录里 `Common/Icon` 的 `HeadIcon`/`BigHeadIcon256`/
`Pet256` 子目录已是 PNG(异色图 `*_1.png`/`JL_*_yise.png`/`*_101_Res.png` 在同目录),
`uv run python scripts/gen_images.py` 转成 webp 落到 `$ROCOM_GAMEDATA_OUT/img/`
(rocom-capture `//go:embed all:data/img`,经 `/img/` 提供)。
35MB 的 `Pet1024` 全身大图暂不 embed(体积考量),需要时把 `Pet1024` 加进 `gen_images.py` 的 `DIRS`。

**可复现 / 防 git 噪音**:同一 libwebp 版本下 PNG→webp 转码是确定性的(webp 无时间戳,
实测同源字节一致)。为此 `pyproject.toml` 把 pillow **钉死精确版本**且 `requires-python>=3.10`
(避免 3.9/3.10 解析到不同 pillow → 不同 libwebp → 全量图片 diff)。`gen_images.py` 还**默认跳过
已存在的 webp**:常规重跑零改动,游戏更新只为新增宠编码,libwebp 万一漂移也不动老文件;
换了 quality 等需整体重编时用 `--force`。

### UI 图标(`gen_icons.py`)

宠物头像/全身图之外的 UI 图标由 `scripts/gen_icons.py` 统一产出到 `$ROCOM_GAMEDATA_OUT/img/<组>/`。
**webp 一律保持原始解包文件名**并按文件名**去重**(多个枚举值/id 复用同一资产时只存一份,故图标
数少于语义键数);语义键(enum/id)→ 原名 的映射由 `gen_gamedata.py` 写进 `names.json`。分组、
两种资源机制:

| 组 | 数据源 | 内容 | 文件数 |
| --- | --- | --- | --- |
| `filter` | `PET_FILTER_CONF.filter_icon` | 系别(属性)18 + 六维 6+6(`AttributeType` 增益类/裸值同图,整数 1-6 即六维编号)+ 搭档标记 10 | 34 |
| `blood` | `PET_BLOOD_CONF.icon` | 24 条血脉主图标(18 属性系 + 6 特殊;异核/黑魔法共用) | 23 |
| `static` | 脚本内 `STATIC` 清单 | 人工挑选的杂项(异色/炫彩/污染、伙伴标记外框) | 5 |
| `worldmap` | 脚本内 `WORLDMAP` 清单 | 人工挑选的大地图 POI(炼金釜/魔力之源/守护地、矿石与植物标记、眠枭庇护所、蓝/黄/紫眠枭之星与精灵果实) | 14 |
| `medal` | `MEDAL_CONF.icon` | 60 枚奖牌小图(BagItem;部分奖牌共用) | 52 |
| `glass` | `HIDDEN_GLASS_CONF` / `PARTICLE_RANDOM_CONF` + 脚本内 `GLASS_FRAMES` | 炫彩色卡的两张遮罩、4 种粒子的粒子层、5 款隐藏炫彩的整卡与标记图(含异色版) | 21 |

> `filter` 组只收 `filter_icons` 实际输出的三组枚举(`gen_icons.py` 的 `FILTER_ENUMS`,与
> `gen_gamedata.py` 同一白名单):`PET_FILTER_CONF` 另有 **PetBloodType**(游戏内血脉筛选)等组,
> 其图标与 `PET_BLOOD_CONF` 同为 XueMai 图集精灵,照单全收会往 `img/filter` 重复转码 21 张
> `img/blood` 已有的图。另注意该表**行 id 会随版本整体重排**,一切取用只认
> `filter_enum_name`/`filter_enum_value`。

**两种机制**:
- **图集精灵(PaperSprite,`filter`/`blood`/`static`/`worldmap`)**——本身不含像素,从图集(`Texture2D`)按 UV
  裁一块。游戏包是 unversioned cooked 资产,`.uexp` 位打包无标签序列化(手写解析不可靠),故 UV
  矩形(`BakedSourceUV`/`BakedSourceDimension`)取自解包出的**属性 .json**(`Frames/` 下);图集本体
  取其引用的 `Textures/` 图集 **PNG**(Frames 包自身无纹理,不出 PNG)。脚本按
  `icon` 引用的完整路径定位 sprite JSON(`ui_pet_attribute_0N` 在 PetUI/PetSystem 两处同名,故不能只
  用 basename),再按同名 basename 回退(同名资产任取等价一份)。
- **整张贴图(`Texture2D`,`medal`)**——解包出的 PNG 直接转码,无需裁切(同宠物头像)。

`WorldMapNpc` 的 `Frames/` 下**混着两类资产**:数字名(`00102` 等)是各自独立的 256×256 `Texture2D`
(NPC 头像,未收录),语义名(`img_*` / `TipDes_*` / `Interestplace_*` 等)才是 PaperSprite;`worldmap`
只挑后者。其 `BakedSourceTexture.ObjectPath` 前缀为 `NRC/Content/...` 而非 `/Game/...`,`game_to_src`
的正则两种都认,无需特殊处理。

用到的图集:`Common/Icon/Species`、`PetUI/Raw/Atlas/PetUI`、`Common/CommonStatic`、
`Common/Icon/XueMai`、`System/BigMap/Raw/Atlas/WorldMapNpc`(各自 `Frames/` 的 .json +
`Textures/` 的 PNG),以及 `Common/Icon/BagItem` 的整张 PNG——全量解包后即齐备,无需单独前置。
webp 转码确定性,默认跳过已存在、`--force` 重编。

**索引/访问**:`gen_gamedata.py` 从 `PET_FILTER_CONF`/`PET_BLOOD_CONF`/`MEDAL_CONF`
(+ `all.pb` 枚举)生成 `names.json` 的三张「语义键 → 图标原名」索引(纯 Bin 配置、无需图片即可
重跑),`gamedata` 据此拼 `<组>/<原名>.webp` 并校验确已 embed(缺则返回空串):

| 索引 | 形状 | 访问器 |
| --- | --- | --- |
| `filter_icons` | `{组名: {枚举整数值: 原名}}` | `SkillDamTypeIcon` / `AttributeTypeIcon` / `PartnerMarkIcon(v)` |
| `blood_icons` | `{血脉id: 原名}` | `BloodIcon(id)` |
| `medal_icons` | `{奖牌id: 原名}` | `MedalIcon(id)` |

`static` / `worldmap` 无数据驱动(游戏侧由 UI 蓝图直接引用,Bin 各表均无引用),故无 Go 访问器,
前端按固定路径 `/img/<组>/<原名>.webp` 引用;新增往 `STATIC` / `WORLDMAP` 清单加一行即可
(sprite .json 已在全量解包内)。经 `//go:embed all:data/img` 收录、`/img/` 提供。血脉的 `icon_1`/`icon_flower` 等变体、
奖牌 `big_icon`(Item190 大图)暂不收录。

### 炫彩色卡(`glass` 组)

游戏里点开宠物名旁的炫彩标记会弹出一张小卡,画的就是这只宠物的炫彩长什么样。画法照抄客户端
`UMG_Pet_DazzlingTips_C:ShowNormalGlassInfo` / `ShowHiddenGlassInfo`,**两种炫彩两条路**:

- **隐藏炫彩**(`glass_type=GT_HIDDEN`,赛季款暗夜拾光/狂欢怪谈/铅字幻梦/月涌狂想 + 常驻款黑白)——
  `HIDDEN_GLASS_CONF.glass_tips_pic` 就是**整张烤好的卡**(配色已画进图里),原样贴上即可。
  卡旁的文案也来自该表:`type=1` 是常驻款(本地化 `mutation_explain_tips_5` =「常驻隐藏」),
  否则按 `active_season` 套 `mutation_explain_tips_3`(「第N赛季限定」);外观名带富文本色标
  (`<span color="#eebf31">暗夜拾光</>`),文字与颜色拆开存,消费方照着上色。
  每款自带标记图 `icon` 与异色炫彩合成版 `yise_icon`(每季一张)。
- **普通炫彩**(`glass_type=GT_COMMON`,`glass_value = (粒子id << 20) | 配色id`)——**没有现成的整图**,
  是三层叠出来的:

  | 层 | 素材 | 着色 |
  | --- | --- | --- |
  | 底 | `img_dazzling_Bg_png`(280×154 圆角矩形) | `COLOR_RANDOM_CONF.ui_color_2` |
  | 中 | `img_dazzling_Bg2_png`(280×108,上半带波浪的那块) | `ui_color_1` |
  | 上 | `PARTICLE_RANDOM_CONF.particle_big_icon`(粒子散布) | 原色,不着色 |

  底两层是**纯白 + alpha 的遮罩**(RGB 全白,形状只在 alpha 里),消费方用 CSS `mask-image` 上色;
  中层原图只有上半 108 像素,顶对齐、高度按原比例(70.13%)给,波谷位置才对得上。
  标记图用 `static` 组的 `img_bolitubian_png` / `img_yisexuancai_png`。

`names.json` 的 `glass` 段是这一切的索引:`{base, wave, hidden{}, colors{}, particles{}}`;
配置里查不到的款(新赛季款)消费方应退回通用炫彩图标、不画卡。

> 对照实机截图逐款验过(暗夜拾光/狂欢怪谈/铅字幻梦/普通/黑白/异色黑白共 6 只,
> `glass_value` 由 pcap 取出):配色、波浪走向、粒子形状与角标全部一致。

## 4. 消费方的解析流程

宠物消息如何解成业务模型(`ToPet`、六维/天分/性格换算、各获得/减少 opcode、盒子与队伍位置等)
属于 rocom-capture,见其 `docs/`。本文只到「生成物」为止。
