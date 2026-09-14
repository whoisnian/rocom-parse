"""提取宠物展示需要的 id->中文名 精简表,输出到 $ROCOM_GAMEDATA_OUT/names.json(默认 build/gamedata,见 outdirs.py)。

数据全部来自本机解包目录(scripts/unpack.sh 从游戏 pak 导出,默认 ~/Downloads/rocom/parsed):
- 名称表: ScriptC/Data/Bin 下游戏自有二进制配置,读 scripts/bin2json.py 解出的
          BinDataCompressed/*.json(unpack.sh 已自动解码;`.bytes`+`.non`+dev_CN 本地化):
  - 种类:   MONSTER_CONF + PET_CONF      id -> name
  - 性格:   AUDIO_NATURE_CONF            nature_id -> name
  - 奖牌:   MEDAL_CONF                   id -> {name, desc}
  - 系别/天分/标记/特长: PET_FILTER_CONF 的 filter_enum_value -> filter_desc / PET_TALENT_CONF
- 枚举/opcode: 游戏描述符 all.pb(ZoneSvrCmd、SkillDamType 等),经 scripts/pbdesc.py 读取。

opcode/枚举与字段号(gen_proto.py 生成的 Go 包)同出 all.pb,天然同版本。
运行(需 uv 管理的 protobuf 依赖):  uv run python scripts/gen_gamedata.py
ROCOM_PROFILE=minimal 时只输出 MINIMAL_KEYS 列出的表(宠物名称/头像/血脉/炫彩/标记的最小子集,见 outdirs.py)。
更新到新版本游戏:重跑 scripts/unpack.sh 刷新解包目录再跑本脚本(原因见 docs/data.md)。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import outdirs
import pbdesc      # 读 all.pb 描述符(依赖 protobuf,uv 管理)

# 名称表:解包目录的游戏二进制配置(ScriptC/Data/Bin);opcode/枚举:游戏描述符 all.pb。
BIN_DIR = os.path.join(outdirs.PARSED, "NRC", "Content", "ScriptC", "Data", "Bin")
ALL_PB = os.path.join(outdirs.PARSED, "NRC", "Content", "ScriptC", "Data", "PB", "all.pb")
OUT = outdirs.GAMEDATA_OUT

# minimal 档:只认宠物本身的名称、头像、血脉、炫彩与伙伴标记(不含地图/蛋/奖牌等)。
MINIMAL_KEYS = ["species", "petbase", "images", "image_base", "blood_names", "blood_icons",
              "static_icons", "filter_icons", "partner_mark", "partner_marks", "glass", "opcodes"]

_FDS = pbdesc.load(ALL_PB)  # 描述符只读一次,enum_dim/opcodes 共用


def rows(table):
    """读一张表已解码的 JSON(scripts/bin2json.py 产出,紧邻 .bytes)为 {id字符串: 行}。"""
    base = table[:-5] if table.endswith(".json") else table
    path = os.path.join(BIN_DIR, "BinDataCompressed", base + ".json")
    if not os.path.exists(path):
        sys.exit(f"缺解码 JSON: {path}\n请先跑 scripts/unpack.sh(或 scripts/bin2json.py)解码 .bytes。")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["RocoDataRows"]


def texkey(ref):
    """从 UE 资产引用 <Cls>'/Game/.../Dir/NAME.NAME' 抠出原始文件名 NAME(PaperSprite/Texture2D 皆可)。"""
    if not isinstance(ref, str):
        return None
    m = re.search(r"/Game/.*/([^/.']+)\.", ref)
    return m.group(1) if m else None


# PET_FILTER 按 enum 名分组: {enum_name: {value_name: desc}};并记录带图标的值 -> 图标原始文件名。
filter_groups = {}
filter_iconed = {}  # {enum_name: {value_name: icon_文件名}}——用于筛选图标索引(只收录有图标者)
for r in rows("PET_FILTER_CONF.json").values():
    en = r.get("filter_enum_name")
    if en:
        filter_groups.setdefault(en, {})[r.get("filter_enum_value")] = r.get("filter_desc")
        if texkey(r.get("filter_icon")):
            filter_iconed.setdefault(en, {})[r.get("filter_enum_value")] = texkey(r.get("filter_icon"))


def enum_dim(enum_name):
    """组合 all.pb 枚举(名->int)与 filter(名->中文)得到 {int: 中文}。"""
    name2int = pbdesc.enum(_FDS, enum_name)
    out = {}
    for vname, desc in filter_groups.get(enum_name, {}).items():
        if vname in name2int:
            out[str(name2int[vname])] = desc
    return out


def enum_icon(enum_name):
    """带图标的枚举整数值 -> 图标原始文件名。webp 保持原始解包文件名(见 gen_icons.py),
    Go 侧据此拼 filter/<原名>.webp。"""
    name2int = pbdesc.enum(_FDS, enum_name)
    out = {}
    for vname, iconname in filter_iconed.get(enum_name, {}).items():
        if vname in name2int:
            out[str(name2int[vname])] = iconname
    return out


def id_icons(table, id_field, icon_field):
    """CONF 行 -> {str(id): 图标原始文件名}(id_field→id,icon_field→资产引用)。
    用于 blood/medal 索引;webp 保持原名,Go 侧拼 <组>/<原名>.webp。"""
    out = {}
    for r in rows(table).values():
        i, k = r.get(id_field), texkey(r.get(icon_field))
        if i is not None and k:
            out[str(int(i))] = k
    return out


def id_names(table, id_field, name_field):
    """CONF 行 -> {str(id): 中文名}(与 id_icons 同键,供图标旁配名)。"""
    out = {}
    for r in rows(table).values():
        i, n = r.get(id_field), r.get(name_field)
        if i is not None and n:
            out[str(int(i))] = n
    return out


# static 组图标:人工挑选的杂项精灵(与 gen_icons.py 的 STATIC 同一批文件),语义键 -> 原始文件名。
# 非 CONF 派生,故就地登记;webp 保持原名(见 gen_icons.py),Go 侧拼 static/<原名>.webp。
STATIC_ICONS = {
    "shiny":          "img_yisetubian_png",   # 异色
    "colorful":       "img_bolitubian_png",   # 炫彩
    "shiny_colorful": "img_yisexuancai_png",  # 异色炫彩(两者兼具)
    "pollution":      "img_emeng_png",        # 污染
    "partner_frame":  "img_collect_png",      # 伙伴标记外框
}


# 种类名：常规宠物在 MONSTER_CONF，彩蛋/特殊宠物在 PET_CONF，两表 id 不重叠，合并取用。
# strip():配置里偶有手滑写进的首尾空格(如「空空颅 」),拼进蛋名一类的模板会露出多余空隙。
species = {k: v["name"].strip() for k, v in rows("MONSTER_CONF.json").items() if v.get("name")}
species.update({k: v["name"].strip() for k, v in rows("PET_CONF.json").items() if v.get("name")})


# ---- 宠物图片索引 ----
# 链路: conf_id(MONSTER/PET 行) --base_id--> PETBASE 基础形态 --> 头像/全身图文件名。
#   头像取自 MODEL_CONF(经 PETBASE.model_conf 关联)的 icon/big_icon;全身图取自 PETBASE.JL_res。
#   文件名【不能用 id 拼】(728 个形态共用他人头像,如 3228 用 3012),故存表;
#   Go 侧按固定目录(HeadIcon/BigHeadIcon256/Pet1024/Pet256)拼出 .webp 路径。
_petbase = rows("PETBASE_CONF.json")
_model = rows("MODEL_CONF.json")

# images: petbase_id -> {h:小头像 b:大头像 p:全身图 ps:全身缩略}(均为不带扩展名的完整文件名)。
#   全身图文件名有两套命名并存:JL_<拼音> 与 img_<系别>_<名><代>_<变体>_Res。
#   故这里**存原样**、不做前缀增删,Go/gen_images 只拼目录与扩展名(剥前缀再回拼会让另一套命名
#   整批丢全身图)。
#   异色变体 sh/sb/sps(头像形如 3010_1,全身图形如 JL_<拼音>_yise / ..._101_Res)仅在与普通版
#   不同时收录;多数宠物异色复用普通美术(shiny_icon==icon、无 JL_shiny_res),不会产生 sh/sb/sps。
images = {}
for pid, p in _petbase.items():
    m = _model.get(str(p.get("model_conf"))) or {}
    entry = {}
    head = texkey(m.get("icon") or m.get("small_icon") or m.get("ui_icon"))
    big = texkey(m.get("big_icon"))
    portrait = texkey(p.get("JL_res"))
    portrait_s = texkey(p.get("JL_small_res"))
    if head:
        entry["h"] = head
    if big:
        entry["b"] = big
    if portrait:
        entry["p"] = portrait
    if portrait_s:
        entry["ps"] = portrait_s
    # 异色变体(仅当与普通版不同):小头像/大头像/全身缩略。
    sh = texkey(m.get("shiny_icon"))
    sb = texkey(m.get("big_shiny_icon"))
    sps = texkey(p.get("JL_small_shiny_res"))
    if sh and sh != head:
        entry["sh"] = sh
    if sb and sb != big:
        entry["sb"] = sb
    if sps and sps != portrait_s:
        entry["sps"] = sps
    if entry:
        images[pid] = entry

# image_base: conf_id -> base_id(petbase),仅当与自身不同;base==自身者 Go 侧回退直查 images。
image_base = {}
for src in ("MONSTER_CONF.json", "PET_CONF.json"):
    for cid, r in rows(src).items():
        b = r.get("base_id")
        if b is not None and str(b) != cid:
            image_base.setdefault(cid, b)

# petbase: petbase_id -> {n:名称 b:图鉴编号 f:形态名 s:进化阶段 e:进化链分组
#   hl/hh:身高下/上限 wl/wh:体重下/上限(原始整数,与 PetData.height/weight 同单位)}。
#   宠物当前形态由 PetData.base_conf_id 直接给出(指向当前 petbase),据此取当前名称/头像/图鉴;
#   conf_id 只指向该线一阶 base,evolved 宠物若用 conf_id 会显示成基础形态。
#   进化链分组 e 由下方连通分量重建(非直接用 pet_evolution_id),Go 侧按 e 分组、stage 排序还原整条链。
#   身高/体重范围逐形态不同(base 越进化数值越大),用于列表 tooltip 显示区间与当前值百分位。
# 进化链分组(重建)。游戏原始的 pet_evolution_id 分组有两个问题:
#   ① 分支进化只跟单条路径——果冻→抹茶布丁,漏掉同为二阶的椰浆布丁/熔岩布丁;
#   ② 把共享"身份背景"的 NPC 混进链——珂赛特老师(背景=厉毒修萝)、希露德老师(背景=公平鸽),
#      以及小游戏变形/剧情/测试/首领(boss)等复制形态,它们与真实图鉴形态同组。
# 真实图鉴形态判据 _real:有图鉴编号(pictorial_book_id)且 petbase_id 在常规区间(<1e7)。
#   * 不能用 legal_petbase==1:传说宠整条链(里奥→灵羽勇士→圣羽翼王、小帕尔→…→龙息帕尔等)
#     legal 均为空,会被整条漏掉。
#   * 有图鉴号:排除无图鉴的纯 NPC(珂赛特老师/希露德老师/药炉,book=None)。
#   * <1e7:排除复制形态——它们虽照抄了图鉴号,但 petbase_id 落在 1.3e7~1.9e7 特殊区间
#     (如"迪莫"16000004、"钨丝贝贝(S2剧情骑乘专用)"19000008、"深渊罗隐"13000169);真实形态
#     的 petbase_id 都是几千量级。
# 对 _real 形态按两类无向边求连通分量:evolution_pet_id(该形态可进化成的目标,含全部分支)
#   + 原 pet_evolution_id(同组互联,兜底季节地区形态)。每个含 ≥2 形态的分量即一条完整进化链
#   (取分量内最小 petbase_id 作分组号);单形态(含 boss/特殊形态如"霜翼领主")不入链。
_real = {int(pid) for pid, p in _petbase.items()
         if p.get("pictorial_book_id") and int(pid) < 10_000_000}
_adj = {pid: set() for pid in _real}
for pid, p in _petbase.items():
    pid = int(pid)
    if pid not in _real:
        continue
    for t in p.get("evolution_pet_id") or []:  # 进化目标(含分支)
        if int(t) in _real:
            _adj[pid].add(int(t))
            _adj[int(t)].add(pid)
    ev = p.get("pet_evolution_id")             # 原分组(兜底,如季节地区形态)
    if isinstance(ev, list) and ev:
        _adj.setdefault(("g", ev[0]), set()).add(pid)  # 用组节点把同组成员连成星形
        _adj[pid].add(("g", ev[0]))
_seen, chain_group = set(), {}
for pid in _real:
    if pid in _seen:
        continue
    stack, comp = [pid], []
    while stack:  # DFS 连通分量(组节点只作桥,不计入成员)
        x = stack.pop()
        if x in _seen:
            continue
        _seen.add(x)
        if not isinstance(x, tuple):
            comp.append(x)
        stack.extend(_adj[x] - _seen)
    if len(comp) >= 2:
        g = min(comp)
        for x in comp:
            chain_group[x] = g

petbase = {}
for pid, p in _petbase.items():
    name = p.get("name")
    if not name:
        continue
    e = {"n": name}
    if p.get("pictorial_book_id"):
        e["b"] = p["pictorial_book_id"]
    if p.get("form"):
        e["f"] = p["form"]
    if p.get("stage"):
        e["s"] = p["stage"]
    if int(pid) in chain_group:
        e["e"] = chain_group[int(pid)]
    eg = p.get("egg_group")
    if eg:  # 蛋组编号列表(1~2 个),对应 egg_group 表的 id
        e["eg"] = eg
    for src, dst in (("height_low", "hl"), ("height_high", "hh"),
                     ("weight_low", "wl"), ("weight_high", "wh")):
        if p.get(src):
            e[dst] = p[src]
    petbase[pid] = e

# ---- 野生宠物 NPC(实时地图的野生宠物图层,见 docs/map.md 5)----
# 大世界里的野生宠物是 NPC 实体:NPC_CONF 行经 traverse_data_param 外键指向 PETBASE_CONF
# (10782→3758 珀尔鼬),据此拿到形态名与头像。只收**可丢球捕捉**的行
# (throwing_interact_type 1=普通野生 / 4=首领;其余映射到 petbase 的行是剧情/家园装饰 NPC,
# 不会作为野生宠刷出),1483 行约 19KB。
# 注:实体是不是野生宠**不靠这张表判**(靠实体自带 height/weight,见 scene.NpcActor.IsWildPet),
# 表只用于显示名称/头像;表里没有的行照样显示,只是没名字。
npc_pets = {k: v["traverse_data_param"][0] for k, v in rows("NPC_CONF.json").items()
            if v.get("throwing_interact_type") in (1, 4)
            and v.get("traverse_data_param") and str(v["traverse_data_param"][0]) in _petbase}

# 其中的**首领**(throwing_interact_type=4:祭礼巨像/女王蜂/钻石蜗/风暴战犬…)另出一张表。
# 它们的 AOI 下发距离比普通野生宠远得多(实测 128-176m,普通的是 80m,见 docs/map.md 6),
# 涂地若把「玩家↔首领」也算成扫过,会把中间那段其实没下发过普通野生宠的地方一并涂上,
# 故涂地跳过首领(见 docs/map.md 7);地图标记不受影响。
npc_bosses = sorted(int(k) for k, v in rows("NPC_CONF.json").items()
                    if v.get("throwing_interact_type") == 4)

# ---- 炫彩(MDT_GLASS / GlassInfo)的外观描述 ----
# 「炫彩」= PetData.mutation_type 的 bit3(Enum.MutationDiffType.MDT_GLASS),与 glass_info 非空
# 严格等价(全部 pcap 363 只变异宠物零反例);glass_info 只是进一步说明**是哪一种**炫彩:
#   glass_type=GT_HIDDEN(2) → glass_value 是 HIDDEN_GLASS_CONF.id,给出隐藏炫彩名(暗夜拾光…);
#   glass_type=GT_COMMON(1) → glass_value 是打包的色号 (particle_id << 20) | color_id
#     (客户端 PetUtils.GetShineDataValue 按 20 位拆,见 UMG_Pet_DazzlingTips_C:ShowNormalGlassInfo),
#     分别查 PARTICLE_RANDOM_CONF(粒子:四角星…)与 COLOR_RANDOM_CONF(配色:亮X暗 - 浅紫橙…)。
# 隐藏炫彩名带富文本标记(<span color="#eebf31">暗夜拾光</>):文字与颜色分开存,
# 颜色就是游戏内那行名字的显示色,前端照用。
#
# 除了名字,这里还把**色卡**(游戏内点开炫彩标记弹出的那张小卡,客户端 UMG_Pet_DazzlingTips_C)
# 的绘制素材一并索引出来,前端据此复刻(图由 gen_icons.py 的 glass 组产出,同为原始文件名):
#   普通炫彩 = 三层叠:底(glass.base)着 ui_color_2 → 上半波浪(glass.wave)着 ui_color_1
#              → 粒子层(particles[i].card,原色不着色);
#   隐藏炫彩 = 一张烤好的整卡(hidden[i].card),配色已画进图里,不叠不着色。
# icon/yise 是这一种炫彩自己的标记图(每季一张,yise 是异色炫彩合成版),用于取代通用炫彩图标。
_glass_l10n = rows("LOCALIZATION_CONF.json")


def _l10n(key, *args):
    msg = (_glass_l10n.get(key) or {}).get("msg") or ""
    return msg.format(*args) if args else msg


def _glass_name_color(name):
    """隐藏炫彩名的富文本显示色(<span color="#eebf31">暗夜拾光</> → #eebf31);没写则空串。"""
    m = re.search(r'color="(#[0-9a-fA-F]{6})"', name)
    return m.group(1) if m else ""


def _glass_season(r):
    """隐藏炫彩的归属文案:常驻款一句「常驻隐藏」,赛季款「第N赛季限定」(文案取自游戏本地化表)。"""
    if r.get("type") == 1:  # Enum.HiddenGlassType.HGT_RESIDENT
        return _l10n("mutation_explain_tips_5")
    season = r.get("active_season") or 0
    return _l10n("mutation_explain_tips_3", season) if season else ""


glass = {
    "base": "img_dazzling_Bg_png",   # 色卡底(圆角矩形遮罩),着 ui_color_2
    "wave": "img_dazzling_Bg2_png",  # 色卡上半波浪遮罩,着 ui_color_1
    "hidden": {str(int(r["id"])): {
        "n": re.sub(r"<[^>]*>", "", r["name"]).strip(),
        "nc": _glass_name_color(r["name"]),
        "s": _glass_season(r),
        "card": texkey(r.get("glass_tips_pic")),
        "icon": texkey(r.get("icon")),
        "yise": texkey(r.get("yise_icon")),
    } for r in rows("HIDDEN_GLASS_CONF.json").values() if r.get("name")},
    "colors": {str(int(r["id"])): {
        "n": r.get("name", ""), "c1": r.get("ui_color_1", ""), "c2": r.get("ui_color_2", ""),
    } for r in rows("COLOR_RANDOM_CONF.json").values() if r.get("id")},
    "particles": {str(int(r["id"])): {
        "n": r.get("name", ""), "card": texkey(r.get("particle_big_icon")),
    } for r in rows("PARTICLE_RANDOM_CONF.json").values() if r.get("id")},
}

# 性格增减维度(权威表，按性格名匹配；维度编号 1生命 2物攻 3魔攻 4物防 5魔防 6速度)。
# NATURE_CONF 推导对个别性格(如平和)的 id 错位，故以名为准。
NATURE_TABLE = {
    "胆小": (6, 2), "急躁": (6, 4), "开朗": (6, 3), "莽撞": (6, 5), "热情": (6, 1),  # 速度增益
    "沉默": (1, 2), "忧郁": (1, 4), "平和": (1, 3), "粗心": (1, 5), "踏实": (1, 6),  # 生命增益
    "大胆": (2, 4), "固执": (2, 3), "调皮": (2, 5), "勇敢": (2, 6), "逞强": (2, 1),  # 物攻增益
    "稳重": (4, 2), "天真": (4, 3), "懒散": (4, 5), "悠闲": (4, 6), "坦率": (4, 1),  # 物防增益
    "聪明": (3, 2), "专注": (3, 4), "偏执": (3, 5), "冷静": (3, 6), "理性": (3, 1),  # 魔攻增益
    "警惕": (5, 2), "温顺": (5, 4), "害羞": (5, 3), "慎重": (5, 6), "焦虑": (5, 1),  # 魔防增益
}
nature_effect = {}
for k, v in rows("AUDIO_NATURE_CONF.json").items():
    if v.get("name") in NATURE_TABLE:
        pos, neg = NATURE_TABLE[v["name"]]
        nature_effect[k] = {"pos": pos, "neg": neg}

# 蛋组(繁殖组):PETBASE_CONF.egg_group 存编号列表,编号即 PET_LIKE_ELEMENT_CONF 的 id
#   (id 1~15 的 pet_like_reason 对应 all.pb 的 PetEggGroup 枚举 PEG_*;16+ 为繁殖组合标记,忽略)。
# 显示名用社区更流行的叫法(下表),游戏配置里的 editor_name1(策划编辑器标签,「名称:描述」格式)
#   仅取「:」后半作为描述保留。editor_name1 本身是官方 Bin 字段,非本地化 UI 串。
EGG_GROUP_NAMES = {
    1: "未发现", 2: "巨灵", 3: "两栖", 4: "昆虫", 5: "天空",
    6: "动物", 7: "妖精", 8: "植物", 9: "拟人", 10: "软体",
    11: "大地", 12: "魔力", 13: "海洋", 14: "龙", 15: "机械",
}
egg_group = {}
for k, v in rows("PET_LIKE_ELEMENT_CONF.json").items():
    gid = v.get("id")
    if gid not in EGG_GROUP_NAMES:  # 只收录 15 个正式蛋组
        continue
    raw = v.get("editor_name1") or ""
    desc = raw.split("：", 1)[1] if "：" in raw else raw  # 「名称:描述」取描述半
    egg_group[str(gid)] = {"name": EGG_GROUP_NAMES[gid], "desc": desc}

# ---- 场景与大地图(实时地图页) ----
# 协议 ZoneEnterSceneRsp / ZoneSceneTeleportNotify 同时给 scene_cfg_id 与 scene_res_cfg_id:
#   scenes:    scene_cfg_id     -> 场景名(SCENE_CONF)
#   scene_res: scene_res_cfg_id -> {n:名称, s:所属 scene_cfg_id}(SCENE_RES_CONF)
#   maps:      有大地图底图的 scene_res_cfg_id -> 投影参数(WORLD_MAP_BLOCK_CONF)
# 只有 4 个场景配了大地图(卡洛西亚大陆/魔法学院/家园室内/家园种植园),其余场景(副本、洞穴、
# 室内小场景)无底图,实时地图页只能显示场景名 + 原始坐标。
scenes = {k: v["scene_name"] for k, v in rows("SCENE_CONF.json").items() if v.get("scene_name")}
# scene_default_res: scene_cfg_id -> 该场景默认 scene_res_id(SCENE_CONF 主行)。移动包只带
# scene_cfg_id,当无法从进入/传送通知得知精确 res 时(如中途开抓、或旧库无缓存),据此兜底定位
# 底图。同 cfg 下的子场景(如魔法学院 10018 属 cfg 103)仍以通知/缓存的精确 res 为准。
scene_default_res = {k: int(v["scene_res_id"]) for k, v in rows("SCENE_CONF.json").items()
                     if v.get("scene_res_id")}
scene_res = {}
for k, v in rows("SCENE_RES_CONF.json").items():
    e = {"n": v.get("scene_res_name") or ""}
    if v.get("scene_id"):
        e["s"] = int(v["scene_id"])
    scene_res[k] = e

# 家园室内(30001)的底图按房屋等级分层(美术资源 Maps/30001/RoomLevel{1..5}),
# 选层用 ZoneEnterSceneRsp.home_room_level;其余场景一张整图。
HOME_INDOOR_RES, HOME_ROOM_LEVELS = 30001, 5
HOME_SCENE_CFG = 301   # 家园(室内 30001 + 种植园 30002 都挂在这个 scene_cfg 下)

maps = {}
for v in rows("WORLD_MAP_BLOCK_CONF.json").values():
    res, center, side = v.get("scene_res_id"), v.get("map_center_position_xyz"), v.get("side_length")
    if not (res and center and side):  # id=999 是无场景的兜底行(只有雷达半径)
        continue
    # 投影(复刻客户端 BigMapUtils.ScenePosToImagePosF):底图左上角 = 中心 - 边长/2,
    # 世界坐标(厘米)→底图归一化坐标 u=(x-ox)/side, v=(y-oy)/side,与底图输出分辨率无关。
    cx, cy = (float(t) for t in center.split(";")[:2])
    side = int(side)
    maps[str(int(res))] = {
        "n": v.get("list_name", ""),
        "ox": int(cx - side / 2),
        "oy": int(cy - side / 2),
        "side": side,
        # 大世界(底图出 4096²、可涂地);家园场景小,出 2048²。发布数据里没有 is_world_map 字段,
        # 用客户端自己的判据 `BigMapUtils.IsHomeScene`(就是 `301 == sceneId`):
        # 所属 scene_cfg 不是家园(301)的即大世界图——即 10003/10018 两张。
        "world": scene_res.get(str(int(res)), {}).get("s") != HOME_SCENE_CFG,
        **({"rooms": HOME_ROOM_LEVELS} if int(res) == HOME_INDOOR_RES else {}),
    }

# 分层地图(洞穴/室内层):LAYERED_WORLD_MAP_CONF。玩家进入洞穴/地下层时,地图把该层的独立切片
# (LayerMap 单张图)叠加到地表底图上,投影用该层自己的 camera_center + Ortho_width(而非底图的
# map_center/side_length)——因为层图是局部放大视图。同一坐标系(scene_res_id),坐标不变。
#
# 选层机制(见 docs/map.md 2):**服务器的区域进/出事件**(ZONE_SCENE_PLAY_ACTS_NOTIFY 里的
# enterted_catcher/left_catcher)给出玩家当前所在区域的 area_func_id,命中本表 area_func_id 即在该层
# (客户端 BigMapModuleData:GetCurMapLayerId 同此)。故本索引给每层带上 `afid`。
# 早前改用「位置点在 AREA_CONF 多边形内」近似,会在洞穴正上方的地表误命中(多边形只有 x/y,
# 而区域触发体是 3D 的),已废弃,多边形不再入库。
# 只收录有 map_resource(即有切片图)的层;地表条目(无图,用底图)跳过。
#
# 层的 scene_res:LAYERED 表有就用(洞穴层=10003);家园层该列为空,只能从其区域行补(=30001)。
# AREA_CONF/AREA_FUNC_CONF 在解包 Bin 目录(为 POI 坐标读取,见下方「大地图 POI」)。
area_conf = rows("AREA_CONF.json")
area_func = rows("AREA_FUNC_CONF.json")


# 层 id -> 该层区域所属 scene_res_id(用于填补 LAYERED 表 scene_res_id 为空的家园层=30001)。
def _extract_layer_res():
    af = {str(int(r["id"])): r for r in area_func.values()}
    ac = {str(int(r["id"])): r for r in area_conf.values()}
    out = {}
    for v in rows("LAYERED_WORLD_MAP_CONF.json").values():
        afid = v.get("area_func_id")
        fr = af.get(str(int(afid))) if afid else None
        if not fr:
            continue
        for aid in fr.get("area_id", []):
            arow = ac.get(str(int(aid)))
            res = int(arow.get("scene_res_id") or 0) if arow else 0
            if res:
                out[str(int(v["id"]))] = res
                break
    return out


layer_res = _extract_layer_res()
layers = {}
for v in rows("LAYERED_WORLD_MAP_CONF.json").values():
    img = v.get("map_resource")
    cc, ow = v.get("camera_center"), v.get("Ortho_width")
    if not (img and cc and ow):
        continue
    ow = int(ow)
    lid = str(int(v["id"]))
    # 所属 scene_res:优先 LAYERED 表,缺失(家园层)时从其区域行补(=30001)。
    lres = int(v.get("scene_res_id") or 0) or layer_res.get(lid, 0)
    layers[lid] = {
        "n": v.get("display_name", ""),
        "grp": v.get("map_layer_group"),     # 同组共享地表底图;组内 sort=1 地表、2+ 楼层
        "res": lres,
        "img": img,                          # 层切片 webp 文件名(保持原名,见 gen_bigmap.py)
        "ox": cc[0] - ow // 2,               # 层投影:同底图公式,参数换成 camera_center/Ortho_width
        "oy": cc[1] - ow // 2,
        "side": ow,
        "afid": int(v.get("area_func_id") or 0),  # 服务器区域进/出事件的 area_func_id,据此选层
    }

# ---- 大地图 POI(实时地图页的图标图层,见 docs/map.md 3)----
# WORLD_MAP_CONF 是「地图元素」表:每行一个可在大地图/罗盘显示的元素,带图标(npcicon_* /
# areaicon_* / npcicon_levelup)与文案(element_text_name),但**没有坐标**。坐标要再走两跳:
#   WORLD_MAP_CONF.npc_refresh_ids → NPC_REFRESH_CONTENT_CONF.refresh_param
#     refresh_type=1 → AREA_CONF[param].center_xyz          (炼金釜/魔力之源/守护地…)
#     refresh_type=4 → SCENE_OBJECT_CONF[param].position_xyz(眠枭庇护所,actor 名 BP_NPCOwl_*)
# 注意 SCENE_OBJECT_AWARD 与 SCENE_OBJECT_CONF **id 相同但含义不同**(前者是可采集物),别取错表。
#
# 图层清单(k=键 / n=中文 / icon=图标原始文件名,须在 gen_icons.py 的 WORLDMAP 组里 / on=默认开启 /
# collect=可收集图层:点带刷新点 id 参与收集判定,前端「收集模式」按此隐藏已收集的点)。
# 非白名单图层的 icon 同时是**匹配依据**:该图标出现在 WORLD_MAP_CONF 行的任意图标字段即算属于本图层。
POI_KINDS = [
    {"k": "mana",        "n": "魔力之源",       "icon": "Interestplace_Campinglan_png",         "on": True},
    {"k": "alchemy",     "n": "炼金釜",         "icon": "Alchemy_png",                          "on": True},
    {"k": "guard",       "n": "守护地",         "icon": "Interestplace_Underground_Unlock_png"},
    {"k": "owl_big",     "n": "大型眠枭庇护所", "icon": "img_gaojimianxiao_weifangman_png"},
    {"k": "owl_small",   "n": "小型眠枭庇护所", "icon": "img_dijimianxiao_weifangman_png"},
    {"k": "star_blue",   "n": "蓝色眠枭之星",   "icon": "img_miaoxianzhixing_lan_png",          "collect": True},
    {"k": "star_yellow", "n": "黄色眠枭之星",   "icon": "img_mianxiaozhixing_huang_png",        "collect": True},
    {"k": "star_purple", "n": "紫色眠枭之星",   "icon": "img_miaoxianzhixing_zi_png",           "collect": True},
    {"k": "part_bugu",   "n": "不咕钟零件",     "icon": "100946",                               "collect": True},
]

# 眠枭之星图层不走 WORLD_MAP 匹配,按 NPC_CONF id 白名单直取刷新行。口径 = 攻略/游戏总数:
# 一颗星 = 独立星 + 光点(交互后出一颗星)+ 石像(星星魔法命中后浮现一颗星,触碰收集;
# 本体不消失,判定特殊,见 docs/map.md 4)。
# 蓝 147 = 98(96@10003+2@10013 风眠圣所)+28+21;黄 228 = 138+55+35;紫 104 = 60+26+18。
# A1=蓝、A2=黄、A2-2=紫(WORLD_MAP 30000/30001/30004 的图标为 lan/huang/zi;靠
# NPC_CONF.min_map_disappear 反查发现这批 NPC——该字段名像「小地图消失距离」,实为
# WORLD_MAP_CONF.id 外键;石像无此绑定,从 NPC_PENDANT_CONF 的挂件星 npc_id 反推)。
# 明确**排除**(否则蓝会虚增到 224、黄 194,见 docs/map.md 3):
#   - 独立星里**刷新区域是多顶点**的行:石像关联的奖励星预设落点(蓝 94 行:51 单星 + 43 多星,
#     区域 2/6/12 顶点),实测收集走石像实体的挂件、这些行未见刷出,不是常驻点位。真星点的
#     刷新区域全部只有 1 个顶点(三色全量验证),该几何判别免维护(紫独立星 60 行无奖励行);
#   - 只带共享/无挂件的装饰石像 NPC(58303-58305/58313-58316/55633/55635/55636,共 248 行):
#     行 id 不在 NPC_PENDANT_CONF 里 = 石像上没挂自己的星,不算点位(带星石像行 id 与挂件表
#     行 id 一一对应,挂件星 npc=50206/50240/50270 分别为蓝/黄/紫);
#   - 50206「增加血上限_眠枭之星」(任务/隐藏特殊星,6 行)与 50240(「准备废弃的数据」,
#     1 行 2 星):虽是挂件星/特殊星 npc,不在攻略总数里,也不进游戏区域计数;
#   - 55196/55197/55198(掉落版)、55530(挖光点)、50270(紫挂件星)、55002-55005:无启用刷新行。
STAR_NPCS = {
    "star_blue":   {55162: "眠枭之星", 55500: "眠枭之星光点", 58308: "眠枭石像"},
    "star_yellow": {55163: "眠枭之星", 55510: "眠枭之星光点", 58318: "眠枭石像"},
    "star_purple": {55601: "眠枭之星", 55602: "眠枭之星光点", 55632: "眠枭石像"},
}
STAR_STANDALONE = {55162, 55163, 55601}  # 独立星(要做多顶点奖励行排除的就这一形态)
STAR_STATUE = {58308, 58318, 55632}      # 石像(行 id 必须在 NPC_PENDANT_CONF 里)

# 不咕钟零件(收集品,道具 104501,MEGAMAP_GATHERING「不咕钟零件」采集物):
# 与眠枭之星同为 NPC 白名单直取刷新行(NPC 55901「A2-2-不咕钟零件」,90 行候选中启用 51 行,
# 与三方攻略全收集数一致)。实体判定与星/光点完全同套(未收集才刷、npc_content_cfg_id=刷新行 id,
# pcap 实测),但**不在 WORLD_EXPLORING_STATISTIC_CONF 里**——服务器不给分区进度,
# 收集模式只走逐点判定,故点位不带候选区域(zone)。
# NPC_WHITELIST 是「按 npc id 白名单取点」图层的总表:星星在此之上另做奖励行/装饰石像排除。
NPC_WHITELIST = {**STAR_NPCS, "part_bugu": {55901: "不咕钟零件"}}

npc_pendant = rows("NPC_PENDANT_CONF.json")

# 防锈校验:WORLD_EXPLORING_STATISTIC_CONF「眠枭之星」行的 npc 清单是官方注册表(服务器
# explore_infos 按同一批 npc_id 计数)。新版本增删星 npc(如再加一色)时在此报警,
# 提醒同步 STAR_NPCS 与 rocom-capture internal/scene/star.go 的 starNpc,避免图层静默缺失。
_official_star = {int(n) for v in rows("WORLD_EXPLORING_STATISTIC_CONF.json").values()
                  if v.get("display_name") == "眠枭之星"
                  for o in (v.get("option") or []) for n in (o.get("npc_id") or [])}
_local_star = {n for m in STAR_NPCS.values() for n in m}
if _official_star != _local_star:
    print(f"!! 眠枭之星 npc 清单与官方探索统计表不一致:官方多 {sorted(_official_star - _local_star)}"
          f" / 本地多 {sorted(_local_star - _official_star)}(需同步 STAR_NPCS 与 star.go)", file=sys.stderr)

npc_refresh = rows("NPC_REFRESH_CONTENT_CONF.json")
scene_object = rows("SCENE_OBJECT_CONF.json")
world_map = rows("WORLD_MAP_CONF.json")

# 只收「游戏里确实会显示」的元素:WORLD_MAP_CONF 有 9 个显示开关(大地图/小地图/罗盘 × 未探索/
# 已探索/未完成)。全空 = 纯触发体,游戏从不画它——如魔力之源的 5 行「空npc,用于分层地图切换」
# (wmc 54001-54005,散落在真实魔力之源 65-260m 外,不加此过滤会在图上多出 5 个假图标)。
# 不能只看大地图开关:有的元素按设计只上小地图/罗盘(如眠枭之星,大地图三个开关全空)。
# 另尊重 is_disable:守护地搬家/换刷新行会留下停用的旧行(雪巨人 wmc 13260 在旧址 1.4km 外、
# 不咕钟 wmc 13256 与现行行重叠),显示开关还开着,只有 is_disable 标记它已废弃。
# 该过滤只影响 WORLD_MAP 匹配的图层;眠枭之星走 STAR_NPCS 白名单,不经此表。
SHOW_FLAGS = [f"{s}_in_{m}" for m in ("map", "minimap", "compass")
              for s in ("unexplored", "explored", "unfinished")]
world_map_all = world_map  # 区域行(1-35)没有显示标志,会被下面滤掉,故先留一份原表给 zones 用
world_map = {k: w for k, w in world_map.items()
             if any(w.get(f) for f in SHOW_FLAGS) and not w.get("is_disable")}


# ---- 区域(zone)与眠枭之星的归属 ----
# 眠枭之星在**游戏内按区域计数**(商店街周边/月牙湖岸/风眠圣所…),服务器在进场景包里下发
# 「每区域已收集/总数」(见 docs/map.md 4)。它用的区域键是该区域营地(魔力之源)的刷新点 id:
# WORLD_MAP_CONF 里带 zone_name + camp_refresh_id 的行 = 区域行。
#
# 区域的**地理范围**走权威外键链(全部为随包发布的产品字段,43 区含新区全覆盖):
#   CAMP_CONF(行 id = 营地刷新点 id)→ area_id(营地管辖区)
#     → AREA_FUNC_CONF.area_id → AREA_CONF 多边形(每区恰一个)
# 相邻管辖区有重叠带,个别星点会同时落入两区且归属无法静态定夺(实测两种决胜规则都会
# 与服务器分区计数矛盾),故 POI 的 zone 是**候选区域列表**:前端仅当列表非空且全部收满才隐藏
# ——绝不误藏(服务器归属必在候选之中,已用回放 star_zone 的分区 tot 全量校验:0 矛盾)。
# 勿再试的歧路见 docs/map.md 4(按区域名匹配 AREA_FUNC 得到的是播报触发体,错 265 点)。
zone_name = {}   # camp_refresh_id -> 区域名
for v in world_map_all.values():
    if v.get("zone_name") and v.get("camp_refresh_id"):
        zone_name[int(v["camp_refresh_id"])] = v["zone_name"]

area_func = rows("AREA_FUNC_CONF.json")
zone_polys = {}  # camp_refresh_id -> [多边形(顶点 xy 列表)]
for k, v in rows("CAMP_CONF.json").items():
    cid = int(k)
    if cid not in zone_name:
        continue  # 非区域营地(副本/家园等)
    f = area_func.get(str(int(v.get("area_id") or 0)))
    for aid in (f.get("area_id") or []) if f else []:
        a = area_conf.get(str(int(aid)))
        pts = [p["position_xyz"] for p in (a.get("pos") or []) if p.get("position_xyz")] if a else []
        if len(pts) >= 3 and a.get("scene_res_id") == 10003:
            zone_polys.setdefault(cid, []).append([(int(p[0]), int(p[1])) for p in pts])
if len(zone_polys) != len(zone_name):
    print(f"!! {len(zone_name) - len(zone_polys)} 个区域缺管辖多边形: "
          f"{[zone_name[c] for c in zone_name if c not in zone_polys]}", file=sys.stderr)


def _in_poly(x, y, poly):
    """射线法:点在多边形内(只用 x/y,管辖区是平面划分)。"""
    inside, n = False, len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def zones_of(x, y):
    """星点 → 候选区域营地 id 列表(即服务器进度里的区域键);不在任何管辖区内返回空。"""
    return sorted(c for c, ps in zone_polys.items() if any(_in_poly(x, y, p) for p in ps))


def _poi_pos(refresh_id):
    """刷新行 → (scene_res_id, x, y, z);禁用/无刷新规则的行与解不出坐标的返回 None。"""
    r = npc_refresh.get(str(int(refresh_id)))
    if not r or r.get("disable"):  # 策划留的废弃/未启用点位
        return None
    # refresh_rule=0/缺失 ⇒ NPC_REFRESH_RULE_CONF 里无此行(规则表没有 id=0),刷新系统从不刷出,
    # 与 disable 同义的另一种废弃写法:4 个炼金釜(700015-700018,游戏里实地无釜,圣所前哨东侧
    # 一例实地核过)与不咕钟守护地旧行 5502266 均属此类;已知不刷出的星星奖励预设落点
    # 94 行也全是 rule=0(它们另有多顶点几何判别兜着)。真实点位全量核对无一 rule=0。
    if not r.get("refresh_rule"):
        return None
    p = r.get("refresh_param")
    row = area_conf.get(str(int(p))) if p else None
    if row and r.get("refresh_type") == 1:
        xyz, res = row.get("center_xyz"), row.get("scene_res_id")
    else:
        row = scene_object.get(str(int(p))) if p else None
        if not row:
            return None
        xyz, res = row.get("position_xyz"), row.get("scene_res_conf_id")
    if not (xyz and res):
        return None
    return int(res), int(xyz[0]), int(xyz[1]), int(xyz[2])


# pois: scene_res_id -> [{k:图层键, x, y, z, n:名称}](世界坐标,厘米,z 为高度;Go 侧用 maps 的
# 同一投影换算成底图归一化 uv,见 gamedata.Project——投影公式只此一处,z 供收集判定的洞穴层守卫,
# 见 pipeline/stars.go)。只收有底图的场景:其余(副本/独立洞穴
# 场景)无从投影。洞穴/楼层的点仍属地表 res(如 10003),会照常落在底图上。
pois = {}
for kind in POI_KINDS:
    icon, seen = kind["icon"], set()
    if kind["k"] in NPC_WHITELIST:
        # 眠枭之星/不咕钟零件:按 npc 白名单直取刷新行(星星的排除项见 STAR_NPCS 注释;
        # 零件无奖励行/石像形态,下面两个排除对它自然不命中)
        star = NPC_WHITELIST[kind["k"]]
        todo = []
        for r in npc_refresh.values():
            nid = int(r.get("npc_id") or 0)
            if nid not in star:
                continue
            # 独立星里石像关联的奖励星预设落点(未见刷出)不算点位:刷新区域是多顶点
            # (真星点全部单顶点,判别依据见 STAR_NPCS 注释)
            if nid in STAR_STANDALONE:
                a = area_conf.get(str(int(r.get("refresh_param") or 0))) if r.get("refresh_type") == 1 else None
                if a and len(a.get("pos") or []) > 1:
                    continue
            # 石像只算真挂着星的(行 id 在挂件表里);装饰石像 NPC 不在 STAR_NPCS,此查为防混入
            if nid in STAR_STATUE and str(int(r["id"])) not in npc_pendant:
                continue
            todo.append(({"name": star[nid]}, int(r["id"])))
    else:
        wids = {k for k, w in world_map.items() if icon in json.dumps(w, ensure_ascii=False)}
        # 地图元素行自带刷新点
        todo = [(w, r) for k, w in world_map.items() if k in wids for r in (w.get("npc_refresh_ids") or [])]
    for owner, rid in todo:
        if rid in seen:
            continue
        seen.add(rid)
        got = _poi_pos(rid)
        if not got:
            continue
        res, x, y, z = got
        if str(res) not in maps:
            continue
        name = owner.get("element_text_name") or owner.get("name") or kind["n"]
        # r=刷新点 id(NPC_REFRESH_CONTENT_CONF.id):服务器下发的 NPC 实体带同一个 id
        #   (ActorInfo.npc.npc_base.npc_content_cfg_id),据此把实体对回这个点位。见 docs/map.md 4。
        # zone=候选区域营地 id 列表(仅眠枭之星;语义见上方区域注释)。
        e = {"k": kind["k"], "r": rid, "x": x, "y": y, "z": z, "n": name}
        if kind["k"].startswith("star"):
            if zz := zones_of(x, y):
                e["zone"] = zz
        pois.setdefault(str(res), []).append(e)

# ---- 稀兽花种(实时地图页的花种图层,见 docs/map.md 8)----
# 大世界同时开着二十来朵花种,每朵里关着一只混血精灵(打赢可捕捉)。花种**不是固定点位**:
# 普通花种每天凌晨 4 点、命定花种每两周周五凌晨 4 点在候选点里重投一遍(捕捉也会让它重投),
# 故点位不能像 POI 那样静态入库——哪些点当前有花只能从流量里的花种列表(0x0375)得知。
# 这里落的是**候选点索引**:刷新行 id -> 世界坐标,供后端把列表里的 content_cfg_id 换成坐标。
#
# 花种 NPC 按 NPC_CONF.name 认(稀兽花种 20128-20145/90001-90018、命定花种 700001-700018),
# **同族内第 k 个 = 血脉 k**(花种列表里的 blood 字段,普通/草/火/水/…/幻,与 PET_BLOOD_CONF 的
# 1-18 一一对应,三份 pcap 逐行核对无例外),大地图图标即该血脉的花图
# (WORLD_MAP_CONF.npc_conf_id 指到花种 NPC 的行,icon 在 BigMapStatic 图集,见 gen_icons.py)。
# 注意是**血脉**不是种族属性:花里孕育的是混血精灵,如 npc 20130(火血脉)里装着虫系的铠甲虫
# (pcap 实测),图标画火、精灵是虫——这正是稀兽花种的看点。
#
# 坐标取 AREA_CONF.pos[0].position_xyz 而**不是** center_xyz:花种的刷新区域行里
# center_xyz 与真实刷出点对不上(命定花种三行全部偏出几十到上百米),而 pos[0] 与流量里
# 0x0152 下发的 npc_pos 逐点吻合(23/23 朵,22 朵完全相等、1 朵差 1 厘米取整)。
FLOWER_KINDS = {"稀兽花种": "wild", "命定花种": "destiny"}

_npc_conf = rows("NPC_CONF.json")
# flower_npcs: NPC_CONF.id -> {"n":花种类别中文, "icon":大地图图标原名(flower/<原名>.webp)}
flower_npcs = {}
_flower_ids = {int(k): v["name"] for k, v in _npc_conf.items() if v.get("name") in FLOWER_KINDS}
_flower_icon = {}   # npc id -> 图标原名(取自 WORLD_MAP_CONF 里指向该 NPC 的行)
for w in world_map_all.values():   # 用未过滤的原表:花种行不参与「是否显示」筛选,只借它拿图标
    nid = w.get("npc_conf_id")
    # 图标引用在本表有两种写法,**两者指的是两张不同的图**,花种要的是前者:
    #   npcicon_unlock        裸文件名(img_cao_png.img_cao_png)→ WorldMapNpc 图集里的**成品**:
    #                         血脉花 + 白描边 + 右上角血脉徽章,100×100,与游戏内大地图一致;
    #   world_map_NPCicon_des 完整资产路径 → BigMapStatic 图集里的**无边剪影**(67×52)。
    # 客户端大地图按裸名取图,故以 npcicon_unlock 为准(花种 48 行全有,18 个裸名在 WorldMapNpc
    # 里一一对得上,含 BigMapStatic 没有的 img_shi/img_gedou/img_feixing);缺它才退回完整路径。
    # texkey 只认完整路径,裸名走 split 取 basename。
    ref = w.get("npcicon_unlock") or w.get("world_map_NPCicon_des") or ""
    if nid in _flower_ids and ref:
        _flower_icon[nid] = texkey(ref) or ref.split(".")[0]
# 少数族内行没写 npc_conf_id(WORLD_MAP 900002/900003…),按「族内序号相同即同属性」补齐:
# 三族的起始 id 分别是 20128 / 90001 / 700001,同序号共用一张属性花图。
_flower_bases = (20128, 90001, 700001)
for nid, kname in sorted(_flower_ids.items()):
    icon = _flower_icon.get(nid)
    if not icon:
        base = max(b for b in _flower_bases if b <= nid)
        idx = nid - base
        icon = next((_flower_icon[o + idx] for o in _flower_bases if o + idx in _flower_icon), "")
    if icon:
        flower_npcs[str(nid)] = {"n": kname, "icon": icon}

# 花里那只精灵的**等级**不在任何下发字段里,是客户端按 (star, spec_flower_seed_id) 查表算的
# (MagicManualUtils.GetFlowerLevel:命定花种查 ACTIVITY_SPEC_FLOWER_SEED_CONF 的
# activity_team_battle_star_level[star],普通花种查 PET_GLOBAL_CONFIG 的
# team_battle_star_level_glass_<star> 的 numList[2])。两者都在花种列表里,故**列表一到就能显示等级**,
# 不必等玩家点开某朵花。实测吻合:5 星普通 → 55、7 星命定(20037/20038/20039)→ 60。
# flower_levels: {"star": {星级: 等级}, "spec": {spec_flower_seed_id: [按星级 1..N 的等级]}}
_glob = rows("PET_GLOBAL_CONFIG.json")
_star_lv = {}
for r in _glob.values():
    m = re.fullmatch(r"team_battle_star_level_glass_(\d+)", str(r.get("key") or ""))
    nums = r.get("numList") or []
    if m and len(nums) >= 2:
        _star_lv[m.group(1)] = int(nums[1])   # Lua 的 numList[2]
flower_levels = {
    "star": _star_lv,
    "spec": {str(int(r["id"])): [int(v) for v in r["activity_team_battle_star_level"]]
             for r in rows("ACTIVITY_SPEC_FLOWER_SEED_CONF.json").values()
             if r.get("activity_team_battle_star_level")},
}

# flowers: 刷新行 id(= 花种列表里的 content_cfg_id)-> [scene_res_id, x, y](世界坐标,厘米)
flowers = {}
for r in npc_refresh.values():
    if int(r.get("npc_id") or 0) not in _flower_ids or r.get("refresh_type") != 1:
        continue
    a = area_conf.get(str(int(r.get("refresh_param") or 0)))
    pos = (a.get("pos") or [{}])[0].get("position_xyz") if a else None
    if not pos or not a.get("scene_res_id") or str(a["scene_res_id"]) not in maps:
        continue
    flowers[str(int(r["id"]))] = [int(a["scene_res_id"]), int(pos[0]), int(pos[1])]

# ---- 精灵蛋与家园小窝(精灵蛋页面 + 实时地图家园图层,见 docs/eggs.md)----

EGG_ITEM_TYPE = 8        # BAG_ITEM_CONF.type:精灵蛋(与 gen_icons.py 同一常量)
BLOOD_NORMAL = 1         # PET_BLOOD_CONF.blood:普通系血脉——人人都有,不进物种名后缀
NEST_INTERACT_TYPE = 3   # FURNITURE_ITEM_CONF.interact_type:可入住宠物的小窝


def _egg_tables():
    """产出 egg_conf(物种蛋)/egg_items(背包蛋物品)/egg_types(蛋品类)/nest_furniture(小窝家具)。

    - egg_conf:  PET_EGG_CONF.id(= 宠物 conf_id) -> {n:物种名, hl/hh/wl/wh:蛋自身的
                 身高体重区间(百分位口径,与成体 PETBASE_CONF 区间不是一套数), t:孵化秒数,
                 p:蛋品类 precious_egg_type(0=普通;异色/炫彩等见 egg_types)}
                 PET_EGG_CONF 不发布 name/form/voice_percent/pet_bond_name(策划专用字段),
                 故 n 由仍发布的字段重建:pet_id → 种类名,再按 PET_INFO_CONF.blood_id 补血脉后缀
                 (PET_BLOOD_CONF.name,如「迪莫（光系血脉）」)。异色由 p/egg_types 单独表达,不进名字。
    - egg_items: BAG_ITEM_CONF 里 type==8 的物品 -> {n:显示名, c:物种 conf_id(随机蛋为 0),
                 img:图标原名(egg/<原名>.webp), npc:窝上蛋 NPC 的 NPC_CONF id,
                 q:物品品质 item_quality, s:排序号 sort_id(两者都是游戏内「品质排序」的键)}
                 显示名按 known_name 模板("{0}的蛋")填物种名;无模板/随机蛋用 name。
                 模板填的是**不带血脉后缀的**种类名——与客户端一致(HandbookModuleData 用
                 GetPetConf(petId).name 填 known_name),血脉只留在 egg_conf.n 里当「孵出谁」。
    - egg_types: EGG_TYPE_CONF 的 precious_egg_type -> {n:品类名(异色精灵蛋…), o:display_order
                 (游戏内品质排序的首要键,越小越靠前), img:小图标原名(egg/<原名>.webp)}
    - nest_furniture: {家具 config_id: {n:家具名, academy:true(仅学院小窝)}},即家园里能住宠物的小窝
                 (FURNITURE_ITEM_CONF.interact_type==3;当前 1001071 精灵小窝、1001072 学院小窝)。
                 学院小窝是精灵学分院的特权家具,与之配对产的蛋**必定继承窝里那只的性格**(玩家实测,
                 见 rocom-capture docs/eggs.md);哪件家具是它由 ACADEMY_PRIVILEGE_CONF 给出
                 (academy_id==AID_PET 且 academy_privilege_type==ACADEMY_PRIV_ADD_HOME_PETBED 的
                 privilege_para1,同客户端 AcademicPrivilegeModuleData:IsPetAcademyHomePetBed)。
    """
    econf, eitems, etypes, nests = {}, {}, {}, {}
    # 重建物种名用:conf_id → pet_info_id → blood_id → 血脉全名(「光系血脉」/「首领血脉」)。
    pet_info = {k: v.get("pet_info_id") for src in ("MONSTER_CONF.json", "PET_CONF.json")
                for k, v in rows(src).items()}
    blood_id = {k: v.get("blood_id") for k, v in rows("PET_INFO_CONF.json").items()}
    blood_full = {k: v["name"] for k, v in rows("PET_BLOOD_CONF.json").items() if v.get("name")}

    def egg_species(conf_id, pet_id):
        """蛋孵出的物种名:种类名 +(非普通)血脉后缀。见本函数 docstring 里的口径说明。"""
        name = species.get(str(pet_id), "")
        b = blood_id.get(str(pet_info.get(conf_id, "")))
        if b and int(b) != BLOOD_NORMAL and str(b) in blood_full:
            name += f"（{blood_full[str(b)]}）"
        return name

    for k, v in rows("PET_EGG_CONF.json").items():
        econf[k] = {"n": egg_species(k, v.get("pet_id", k)),
                    "hl": v.get("height_low", 0), "hh": v.get("height_high", 0),
                    "wl": v.get("weight_low", 0), "wh": v.get("weight_high", 0), "t": v.get("hatch_data", 0),
                    "p": v.get("precious_egg_type", 0)}
    for k, v in rows("BAG_ITEM_CONF.json").items():
        if v.get("type") != EGG_ITEM_TYPE:
            continue
        conf = 0
        for beh in v.get("item_behavior") or []:
            for r in beh.get("ratio") or []:
                if str(r) in econf:
                    conf = int(r)
                    break
        name = v.get("known_name") or v.get("name") or ""
        if "{0}" in name:
            name = name.replace("{0}", species.get(str(conf), "未知精灵"))
        e = {"n": name, "c": conf, "img": texkey(v.get("icon", "")),
             "q": v.get("item_quality", 0), "s": v.get("sort_id", 0)}
        if v.get("npcid"):
            e["npc"] = int(v["npcid"])
        eitems[k] = e
    # 蛋品类:precious_egg_type 是键(不是行 ID);没有该字段的那行即「普通蛋」(0),
    # 它没有名字/图标,只提供排序号(100000,排在所有特殊蛋之后)。
    for v in rows("EGG_TYPE_CONF.json").values():
        t = {"o": v.get("display_order", 0)}
        if v.get("name"):
            t["n"] = v["name"]
        if texkey(v.get("small_icon") or v.get("icon")):
            t["img"] = texkey(v.get("small_icon") or v.get("icon"))
        etypes[str(v.get("precious_egg_type", 0))] = t
    aid_pet = pbdesc.enum(_FDS, "AcademyType")["AID_PET"]
    priv_petbed = pbdesc.enum(_FDS, "AcademyPrivType")["ACADEMY_PRIV_ADD_HOME_PETBED"]
    academy_beds = {str(v.get("privilege_para1")) for v in rows("ACADEMY_PRIVILEGE_CONF.json").values()
                    if v.get("academy_id") == aid_pet and v.get("academy_privilege_type") == priv_petbed}
    for k, v in rows("FURNITURE_ITEM_CONF.json").items():
        if v.get("interact_type") == NEST_INTERACT_TYPE:
            nests[k] = {"n": v.get("name", "")}
            if k in academy_beds:
                nests[k]["academy"] = True
    if missing := academy_beds - set(nests):
        print(f"!! ACADEMY_PRIVILEGE_CONF 指的学院小窝 {sorted(missing)} 不在 FURNITURE_ITEM_CONF 的小窝里"
              f"(interact_type!={NEST_INTERACT_TYPE}),需核对", file=sys.stderr)
    return econf, eitems, etypes, nests


def _size_medals():
    """按尺寸/嗓音百分位自动授予的奖牌(MEDAL_TASK_CONF 里那四条)。

    -> [{id, n:奖牌名, d:维度(2=体重 3=嗓音), lo, hi}](蛋卡片上是纯文字标签,不取图标)
    **desc 里写的是「身高」,实际判的是体重**:本机 812 只宠物里戴「小不点」的体重百分位
    全在 [0,2](与配置窗口严丝合缝),而身高百分位到 5;「大块头」两者都 ≥98.1 不区分。
    蛋的百分位孵化后原样保留(见 docs/eggs.md),故体重那两枚破壳前就能算出来;
    嗓音那两枚要等破壳(PetEggBrief 没有 voice 字段)。

    MEDAL_TASK_CONF 只发布 id/desc/count,判定字段(get_condition/condition_data1/2)是策划专用、
    不随包(见 docs/data.md「策划字段剥离」)。故维度按 task id 固定
    (文本推不出来:desc 说身高、实判体重),百分位窗口仍从 desc 的「前/末/最高/最低 N%」读,
    窗口若被改动能跟着变;下面的防锈校验兜住该表增删行。
    """
    medals = rows("MEDAL_CONF.json")
    by_task = {}
    for m in medals.values():
        for t in m.get("task_ids") or []:
            by_task[str(t)] = m
    tasks = rows("MEDAL_TASK_CONF.json")
    out = []
    for k, dim in SIZE_MEDAL_DIMS.items():
        v, m = tasks.get(str(k)), by_task.get(str(k))
        win = _percentile_window((v or {}).get("desc", ""))
        if not v or not m or not win:
            print(f"!! 百分位奖牌 task {k} 已失效(行在={bool(v)} 奖牌在={bool(m)} "
                  f"窗口={win});需按 desc 重新核对 SIZE_MEDAL_DIMS", file=sys.stderr)
            continue
        out.append({"id": int(m["id"]), "n": m.get("name", ""),
                    "d": dim, "lo": win[0], "hi": win[1]})
    extra = [k for k, v in tasks.items()
             if int(k) not in SIZE_MEDAL_DIMS and _percentile_window(v.get("desc", ""))]
    if extra:
        print(f"!! MEDAL_TASK_CONF 新增按百分位授予的奖牌 {extra},需补 SIZE_MEDAL_DIMS", file=sys.stderr)
    return sorted(out, key=lambda x: x["id"])


def _percentile_window(desc: str):
    """「精灵的身高范围在前2%范围内(最高)」-> (98, 100);末/最低 N% -> (0, N)。"""
    m = re.search(r"范围在(前|末|最高|最低)(\d+)%范围内", desc)
    if not m:
        return None
    n = int(m.group(2))
    return (100 - n, 100) if m.group(1) in ("前", "最高") else (0, n)


# 百分位奖牌的维度:2=体重、3=嗓音(原 condition_data1,已随策划字段剥离)。
SIZE_MEDAL_DIMS = {1001: 2, 1002: 2, 1025: 3, 1026: 3}

egg_conf, egg_items, egg_types, nest_furniture = _egg_tables()

# 伙伴标记选择器里的那几个:按 PET_FILTER_CONF 的 PetPartnerMarkType 行(含「无」)、按 id 顺序。
_ppmt_name2int = pbdesc.enum(_FDS, "PetPartnerMarkType")
partner_marks = [
    {"v": _ppmt_name2int[r["filter_enum_value"]], "e": r["filter_enum_value"], "icon": texkey(r.get("filter_icon"))}
    for r in sorted((r for r in rows("PET_FILTER_CONF.json").values()
                     if r.get("filter_enum_name") == "PetPartnerMarkType"), key=lambda r: int(r["id"]))
    if r["filter_enum_value"] in _ppmt_name2int
]

size_medals = _size_medals()

data = {
    "species": species,
    # 蛋组: id -> {name:社区流行名, desc:官方描述}。petbase[].eg 引用这些 id。
    "egg_group": egg_group,
    # 场景名与大地图投影参数(见上)。底图 webp 由 gen_bigmap.py 生成,文件名即 scene_res_cfg_id
    # (家园室内为 30001_<房屋等级>),Go 侧拼 bigmap/<名>.webp。
    "scenes": scenes,
    "scene_default_res": scene_default_res,
    "scene_res": scene_res,
    "maps": maps,
    # 分层地图(洞穴/地下层):层id -> {名称,组,scene_res,层图,cave前缀,投影 ox/oy/side}。见上。
    "layers": layers,
    # 大地图 POI(实时地图页可开关的图标图层):poi_kinds 是图层清单(有序,on=默认开启),
    # pois 是 scene_res_id -> [{k:图层键, r:刷新点id, x, y, z:高度, n:名称, zone:候选区域(仅星星)}]。
    # 见上与 docs/map.md 3/4。
    "poi_kinds": POI_KINDS,
    "pois": pois,
    # 区域: 营地(魔力之源)刷新点 id -> 区域名。服务器的眠枭之星收集进度按此键下发(3.4)。
    "zones": {str(k): v for k, v in zone_name.items()},
    "nature": {k: v.get("name", "") for k, v in rows("AUDIO_NATURE_CONF.json").items() if v.get("name")},
    "nature_effect": nature_effect,
    "skill_dam_type": enum_dim("SkillDamType"),
    "talent_rate": enum_dim("PetTalentRate"),
    "partner_mark": enum_dim("PetPartnerMarkType"),
    # 伙伴标记选择器:游戏只给 PET_FILTER_CONF 登记的那几个(不是枚举全部 16 个),按配置 id 顺序,
    # [{v: 枚举整数值, e: 枚举名, icon: 图标原名}];filter_desc 全是「标记」,靠图标区分,不编中文名。
    "partner_marks": partner_marks,
    # UI 图标索引: 语义键 -> 图标原始文件名(webp 保持原名,gen_icons.py 裁出/转码)。
    #   filter_icons: {组名: {枚举整数值: 原名}} 系别(属性)/六维(增益类与裸值)/搭档标记三组。
    #   blood_icons:  {血脉id: 原名}(PET_BLOOD_CONF)。medal_icons: {奖牌id: 原名}(MEDAL_CONF)。
    # Go 侧据此拼 <组>/<原名>.webp。
    "filter_icons": {
        "skill_dam_type": enum_icon("SkillDamType"),
        "attribute_type": enum_icon("AttributeType"),
        "partner_mark": enum_icon("PetPartnerMarkType"),
    },
    "blood_icons": id_icons("PET_BLOOD_CONF.json", "blood", "icon"),
    "blood_names": id_names("PET_BLOOD_CONF.json", "blood", "blood_name"),
    "medal_icons": id_icons("MEDAL_CONF.json", "id", "icon"),
    # 杂项静态图标(异色/炫彩/污染/伙伴外框):语义键 -> 原名,Go 侧拼 static/<原名>.webp。
    "static_icons": STATIC_ICONS,
    # 特长：仅取 PET_TALENT_CONF 里 filter_enum_value=PTFN_TALENT_* 的固定特长，
    # 避免误用非特长条目;id=502 的 name 为"勇敢"，游戏内显示为"无畏"。
    "speciality": {
        k: ("无畏" if int(k) == 502 else v["name"])
        for k, v in rows("PET_TALENT_CONF.json").items()
        if str(v.get("filter_enum_value", "")).startswith("PTFN_TALENT") and v.get("name")
    },
    "medal": {k: {"name": v.get("name", ""), "desc": v.get("desc", "")}
              for k, v in rows("MEDAL_CONF.json").items() if v.get("name")},
    # 图片索引:petbase 形态 -> 文件名;conf_id -> petbase(经 base_id,与自身相同者省略)。
    "images": images,
    "image_base": image_base,
    # petbase 形态元数据(名称/图鉴号/形态名/阶段/进化链分组),按 base_conf_id 取当前形态。
    "petbase": petbase,
    # 野生宠物 NPC: NPC_CONF.id -> petbase_id(取名称/头像)。实时地图的野生宠物图层用,
    # 见上与 docs/map.md 5。
    "npc_pets": npc_pets,
    "npc_bosses": npc_bosses,
    # 稀兽花种(实时地图页的花种图层,见上与 docs/map.md 8):
    #   flower_npcs: 花种 NPC_CONF.id -> {n:类别(稀兽花种/命定花种), icon:图标原名(flower/<原名>.webp)}
    #   flowers:     刷新行 id(花种列表里的 content_cfg_id)-> [scene_res_id, x, y] 候选点世界坐标
    "flower_npcs": flower_npcs,
    "flowers": flowers,
    "flower_levels": flower_levels,
    # 炫彩:隐藏炫彩(名称/归属/整卡)、普通炫彩的配色与粒子,以及色卡两张遮罩(见上)。
    "glass": glass,
    # 精灵蛋:物种蛋区间/孵化时长、背包蛋物品(显示名/图标/窝上 NPC)、家园小窝家具。见上与 3.6。
    "egg_conf": egg_conf,
    "egg_items": egg_items,
    "egg_types": egg_types,
    "size_medals": size_medals,
    "nest_furniture": nest_furniture,
    # opcode 整数 -> ZoneSvrCmd 名称(供界面展示事件名)。
    # 取自 all.pb 的 ZoneSvrCmd 全集(含 6531=ZONE_SCENE_THROW_CATCH_FINISH_RSP 等),
    # 与 gen_proto.py 的 Go 包同源同版本,无需手工补充。
    "opcodes": {str(v): k for k, v in pbdesc.enum(_FDS, "ZoneSvrCmd").items()},
}

if outdirs.PROFILE == "minimal":
    data = {k: data[k] for k in MINIMAL_KEYS}

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "names.json"), "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

for k, v in data.items():
    print(f"  {k}: {len(v)} 项")
print("-> " + os.path.join(OUT, "names.json"))
