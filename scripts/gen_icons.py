"""统一 UI 图标生成器:裁切/转码解包图标为 webp,落到 $ROCOM_GAMEDATA_OUT/img/<组>/(默认 build/gamedata/img,见 outdirs.py)。

两种资源机制:
  - 图集精灵(Paper2D PaperSprite):本身不含像素,从图集(Texture2D)按 UV 裁一块。UV 取自
    解包出的属性 .json,图集取自解包出的 PNG。用于 filter / blood / static。
  - 整张贴图(Texture2D):解包出的 PNG 直接转码(同宠物头像),无需裁切。用于 medal。

**命名保持原始解包文件名**:webp 文件名即游戏资产名(如 `ui_icon_species_04_png.webp` /
`img_huo_png.webp` / `img_MedalIcon_Huge.webp`),按 basename **去重**(多个枚举值/id 复用同一资产
时只存一份)。语义映射(enum/id → 文件名)由 gen_gamedata.py 从解包配置写进 names.json 的
`filter_icons`/`blood_icons`/`medal_icons`;本脚本只产图,不涉及 enum/id。

各组数据源:
  - filter:   PET_FILTER_CONF.filter_icon(系别/六维/搭档标记的精灵)  → img/filter/
  - blood:    PET_BLOOD_CONF.icon(24 血脉主图标精灵)                 → img/blood/
  - static:   下方 STATIC 清单(人工挑选的杂项精灵)                   → img/static/
  - worldmap: 下方 WORLDMAP 清单(人工挑选的大地图 POI 精灵)          → img/worldmap/
  - flower:   稀兽/命定花种的大地图属性花图(WORLD_MAP_CONF 指到花种 NPC 的行) → img/flower/
  - medal:    MEDAL_CONF.icon(BagItem 奖牌小图,整张贴图)            → img/medal/
  - egg:      BAG_ITEM_CONF 里 type==8 的精灵蛋 icon(整张贴图)      → img/egg/
  - glass:    炫彩色卡的两张遮罩 + 粒子层 + 隐藏炫彩整卡与标记图     → img/glass/

webp 转码确定性(同 libwebp 下同源字节一致),默认跳过已存在;--force 强制重编(见 gen_images.py)。
前置:scripts/unpack.sh 全量解包(uasset → 属性 .json,纹理 → PNG,同名同目录)。
运行(需 uv 管理的 pillow):
    uv run python scripts/gen_icons.py [解包根目录(含 Content 的一级,默认 parsed/NRC)] [--force]
"""
import json
import os
import re
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import outdirs

FORCE = "--force" in sys.argv[1:]
_pos = [a for a in sys.argv[1:] if not a.startswith("-")]
SRC = _pos[0] if _pos else os.path.join(outdirs.PARSED, "NRC")
BIN_DIR = os.path.join(SRC, "Content", "ScriptC", "Data", "Bin")
OUT_ROOT = outdirs.IMG_OUT
QUALITY = 90  # 与 gen_images 一致;UI 图标够用且体积小

# static 组:人工挑选的杂项精灵 {sprite 名(即原始 basename): 中文说明}。均在 Common/CommonStatic 图集。
STATIC = {
    "img_collect_png":     "伙伴标记外框",
    "img_emeng_png":       "污染图标",
    "img_yisetubian_png":  "异色图标",
    "img_bolitubian_png":  "炫彩图标",
    "img_yisexuancai_png": "异色炫彩图标",
}

# worldmap 组:人工挑选的大地图 POI 精灵,均在 System/BigMap/Raw/Atlas/WorldMapNpc 图集。
# 该图集的 Frames 下混着两类资产:数字名(00102 等)是独立 Texture2D(NPC 头像),
# 语义名的才是 PaperSprite;这里只挑后者,故与 static 同走 crop_sprite。
# 眠枭的两张「之星」资产名把拼音写反了(mianxiao / miaoxian),同一图两色,非笔误勿改。
WORLDMAP = {
    "Alchemy_png":                          "炼金釜",
    "Interestplace_Campinglan_png":         "魔力之源",
    "Interestplace_Underground_Unlock_png": "守护地",
    "img_MapIcon_Ore_png":                  "矿石标记",
    "img_MapIcon_PetPlant_png":             "植物标记",
    "img_dijimianxiao_weifangman_png":      "小型眠枭庇护所",
    "img_gaojimianxiao_weifangman_png":     "大型眠枭庇护所",
    "img_mianxiaozhixing_huang_png":        "黄色眠枭之星",
    "img_miaoxianzhixing_lan_png":          "蓝色眠枭之星",
    "img_miaoxianzhixing_zi_png":           "紫色眠枭之星",
    "owl_worldmap_fruit_A1_png":            "蓝色精灵果实",
    "owl_worldmap_fruit_A2_png":            "黄色精灵果实",
    "owl_worldmap_fruit_A3_png":            "紫色精灵果实",
}

# flower 组:稀兽花种/命定花种的大地图图标(18 种**血脉**各一张花图,稀兽与命定共用同一批;
# 花里孕育的是混血精灵,图标画的是它的血脉而非种族属性,见 gen_gamedata.py 的花种段)。
# 它们在 **BigMapStatic** 图集(与 worldmap 组的 WorldMapNpc 不同),且文件名(img_cao_png、
# img_huo_png…)与 WorldMapNpc/CommonStatic 里的同名精灵**撞名不同图**,故:
#   ①不把 BigMapStatic 加进 ATLAS_DIRS(basename 回退会选错图集),只走 WORLD_MAP_CONF 里的
#     完整资产路径 world_map_NPCicon_des;
#   ②单独出一组 img/flower/,免得与 img/worldmap/ 的同名 webp 互相覆盖。
# 花种 NPC 按 NPC_CONF.name 认(与 gen_gamedata.py 的 FLOWER_KINDS 同一判据)。
FLOWER_KINDS = ("稀兽花种", "命定花种")


# 图层图例用的通用花种图标(不属于任何属性),与属性花图同图集。
FLOWER_GENERIC = "/Game/NewRoco/Modules/System/BigMap/Raw/Atlas/BigMapStatic/Frames/img_icon_huazhong_png"


def flower_icon_refs():
    """花种大地图图标的完整资产引用(/Game/…/BigMapStatic/Frames/img_<属性>_png)+ 通用图例图。

    图标引用取 world_map_NPCicon_des(完整路径)而非 npcicon_unlock(裸文件名):后者有三行
    (石/格斗/飞行系)写着解包树里根本不存在的资产名,前者才是现行的 img_yan/img_wu/img_yi。
    """
    yield FLOWER_GENERIC
    flowers = {int(k) for k, r in load_rows("NPC_CONF").items() if r.get("name") in FLOWER_KINDS}
    for r in load_rows("WORLD_MAP_CONF").values():
        if r.get("npc_conf_id") not in flowers:
            continue
        m = re.search(r"/Game/[^']+", str(r.get("world_map_NPCicon_des") or ""))
        if m:
            yield m.group(0)


# glass 组:炫彩色卡(见 docs/data.md 的炫彩段与客户端 UMG_Pet_DazzlingTips_C)。
# 普通炫彩的卡**不是一张现成图**,而是三层叠出来的,故这里把三层的素材都导出、前端再合成:
#   ① img_dazzling_Bg_png (280×154 圆角矩形)着 COLOR_RANDOM_CONF.ui_color_2;
#   ② img_dazzling_Bg2_png(280×108 上半波浪)着 ui_color_1,压在①上;
#   ③ PARTICLE_RANDOM_CONF.particle_big_icon(粒子层)原色叠最上,不着色。
# ①②是纯白+alpha 的遮罩(RGB 全白,只有 alpha 有形状),前端用 CSS mask 上色,故原样导出。
# 隐藏炫彩不拼图:HIDDEN_GLASS_CONF.glass_tips_pic 就是整张烤好的卡(配色已画进图里)。
GLASS_FRAMES = {
    "img_dazzling_Bg_png":  "色卡底(圆角矩形遮罩)",
    "img_dazzling_Bg2_png": "色卡上半波浪遮罩",
}


# worldmap 组的整张贴图补充:游戏大地图钉直接复用背包图标的收集品(MEGAMAP_CONF.icon 即
# BagItem 编号),不在 WorldMapNpc 图集里,走 copy_texture(basename 回退命中 BagItem 目录)。
WORLDMAP_TEX = {
    "100946": "不咕钟零件",
}


# ── 基础设施 ──────────────────────────────────────────────

def load_rows(table: str) -> dict:
    path = os.path.join(BIN_DIR, "BinDataCompressed", table + ".json")
    if not os.path.exists(path):
        sys.exit(f"缺解码 JSON: {path}\n请先跑 scripts/unpack.sh(或 scripts/bin2json.py)解码 .bytes。")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["RocoDataRows"]


def game_to_src(ref: str) -> str:
    """/Game/A/B/x.x 或裸 basename -> <SRC>/Content/A/B/x(不含扩展名;裸名则 <SRC>/Content/x)。"""
    m = re.search(r"(?:/Game/|/Content/|^Content/)(.+)", ref)
    rel = m.group(1) if m else ref
    rel = re.sub(r"\.[^./]*$", "", rel)  # 去掉最后的 .Name 或 .0 序号
    return os.path.join(SRC, "Content", rel)


def basename(ref: str) -> str:
    """资产引用 -> 原始文件名(basename,不含扩展名/序号)。"""
    return os.path.basename(game_to_src(ref))


# basename 回退只在本脚本用到的图集/图目录内检索:全量解包树里同名资产遍地都是
# (如 Alchemy_png 在 CompassIcon/WorldMapNpc 两图集同名不同图),全树索引会选错;
# 限定目录才有唯一性,顺带免去数十万文件的全树遍历。
ATLAS_DIRS = [
    "NewRoco/Modules/System/Common/Icon/Species",
    "NewRoco/Modules/System/Common/Icon/XueMai",
    "NewRoco/Modules/System/Common/CommonStatic",
    "NewRoco/Modules/System/PetUI/Raw/Atlas/PetUI",
    "NewRoco/Modules/System/PetUI/PetUIStatic",
    "NewRoco/Modules/System/BigMap/Raw/Atlas/WorldMapNpc",
    "NewRoco/Modules/System/Common/Icon/BagItem",
    # 少数精灵蛋图标只有大图版本(Item190),BagItem 下没有同名小图:放在最后作 basename 兜底,
    # 不影响前面各目录已能命中的名字。
    "NewRoco/Modules/System/Common/Icon/Item190",
]

_by_base: dict[str, dict[str, str]] = {}


def find(ref: str, ext: str) -> str:
    """定位解包文件:先按引用完整路径,再按 basename 在 ATLAS_DIRS 内回退(同名精灵散在多处时)。"""
    p = game_to_src(ref) + ext
    if os.path.exists(p):
        return p
    if ext not in _by_base:
        idx = {}
        for d in ATLAS_DIRS:
            for root, _, files in os.walk(os.path.join(SRC, "Content", d)):
                for f in files:
                    if f.endswith(ext):
                        idx.setdefault(f, os.path.join(root, f))
        _by_base[ext] = idx
    return _by_base[ext].get(os.path.basename(p), "")


def crop_sprite(ref: str, dst: str) -> str | None:
    """PaperSprite:读属性 JSON 的 UV,从图集 PNG 裁切并写 webp。返回失败原因或 None。"""
    jf = find(ref, ".json")
    if not jf:
        return "缺 JSON"
    with open(jf, encoding="utf-8") as f:
        sp = next((o for o in json.load(f) if o.get("Type") == "PaperSprite"), None)
    if sp is None:
        return "非 PaperSprite"
    P = sp["Properties"]
    uv = P.get("BakedSourceUV") or {"X": 0, "Y": 0}  # 零值在导出 JSON 里被省略,默认 (0,0)
    dim = P["BakedSourceDimension"]
    png = find(P["BakedSourceTexture"]["ObjectPath"], ".png")
    if not png:
        return "缺图集"
    x, y, w, h = int(uv["X"]), int(uv["Y"]), int(dim["X"]), int(dim["Y"])
    Image.open(png).convert("RGBA").crop((x, y, x + w, y + h)).save(
        dst, "WEBP", quality=QUALITY, method=4)
    return None


def copy_texture(ref: str, dst: str) -> str | None:
    """Texture2D:整张 PNG 直接转码。返回失败原因或 None。"""
    png = find(ref, ".png")
    if not png:
        return "缺 PNG"
    Image.open(png).convert("RGBA").save(dst, "WEBP", quality=QUALITY, method=4)
    return None


# ── 各组:枚举图标资产引用 ─────────────────────────────────

# filter 组只收 names.json filter_icons 实际输出的三组(与 gen_gamedata 同一白名单):
# PET_FILTER_CONF 另有 PetBloodType 组(游戏内血脉筛选),其图标与 PET_BLOOD_CONF
# 的血脉主图标同为 XueMai 图集精灵,照单全收会往 img/filter 重复转码 21 张 img/blood 已有的图。
FILTER_ENUMS = {"SkillDamType", "AttributeType", "PetPartnerMarkType"}

# 精灵蛋在 BAG_ITEM_CONF 里的 type(与 gen_gamedata.py 的 EGG_ITEM_TYPE 同一常量)
EGG_ITEM_TYPE = 8


def icon_refs(table: str, field: str, enums: set | None = None):
    for r in load_rows(table).values():
        if enums and r.get("filter_enum_name") not in enums:
            continue
        ic = r.get(field)
        if isinstance(ic, str) and ic:
            m = re.search(r"/Game/[^']+", ic)
            if m:
                yield m.group(0)


def egg_icon_refs():
    """精灵蛋(BAG_ITEM_CONF.type==8)的背包图标;近 300 张,同一物种的多种蛋共用一张。"""
    for r in load_rows("BAG_ITEM_CONF").values():
        if r.get("type") != EGG_ITEM_TYPE:
            continue
        ic = r.get("icon")
        if isinstance(ic, str) and ic:
            m = re.search(r"/Game/[^']+", ic)
            if m:
                yield m.group(0)


def eggtype_icon_refs():
    """蛋品类角标(EGG_TYPE_CONF:异色/炫彩/珍贵/唯一…):Common/Raw/Frames 下的图集精灵,
    取 small_icon(卡片上是个二十来像素的小圆标),缺则回退 icon。与蛋图同放 img/egg/。"""
    for r in load_rows("EGG_TYPE_CONF").values():
        ic = r.get("small_icon") or r.get("icon")
        if isinstance(ic, str) and ic:
            m = re.search(r"/Game/[^']+", ic)
            if m:
                yield m.group(0)


def glass_icon_refs():
    """炫彩色卡与标记图:两张遮罩 + 各粒子的色卡粒子层(particle_big_icon)
    + 各隐藏炫彩的整卡(glass_tips_pic)与标记图(icon / 异色版 yise_icon)。"""
    yield from GLASS_FRAMES
    yield from icon_refs("PARTICLE_RANDOM_CONF", "particle_big_icon")
    for field in ("glass_tips_pic", "icon", "yise_icon"):
        yield from icon_refs("HIDDEN_GLASS_CONF", field)


def gen_group(group: str, refs, writer) -> int:
    """按 basename 去重,逐个 writer(ref, dst) 产出 <group>/<原名>.webp。"""
    out = os.path.join(OUT_ROOT, group)
    os.makedirs(out, exist_ok=True)
    uniq = {}
    for ref in refs:
        uniq.setdefault(basename(ref), ref)  # 同名只处理一次
    done = kept = miss = 0
    for name, ref in sorted(uniq.items()):
        dst = os.path.join(out, name + ".webp")
        if os.path.exists(dst) and not FORCE:
            kept += 1
            continue
        why = writer(ref, dst)
        if why:
            print(f"  {group} {name}: {why}")
            miss += 1
        else:
            done += 1
    print(f"  {group:7} 新转 {done:3}  已存在跳过 {kept:3}  源缺失 {miss:3}  (唯一 {len(uniq)})")
    return done + kept


def main():
    if not os.path.isdir(SRC):
        sys.exit(f"源目录不存在: {SRC}\n请先跑 scripts/unpack.sh 解包,或传解包根目录/设 ROCOM_PARSED。")
    total = 0
    total += gen_group("filter", icon_refs("PET_FILTER_CONF", "filter_icon", FILTER_ENUMS), crop_sprite)
    total += gen_group("blood", icon_refs("PET_BLOOD_CONF", "icon"), crop_sprite)
    total += gen_group("static", list(STATIC), crop_sprite)
    total += gen_group("glass", glass_icon_refs(), crop_sprite)
    if outdirs.PROFILE == "minimal":   # 最小档只要以上四组
        print(f"-> {OUT_ROOT}(minimal 档)")
        return
    total += gen_group("worldmap", list(WORLDMAP), crop_sprite)
    total += gen_group("worldmap", list(WORLDMAP_TEX), copy_texture)
    total += gen_group("flower", flower_icon_refs(), crop_sprite)
    total += gen_group("medal", icon_refs("MEDAL_CONF", "icon"), copy_texture)
    total += gen_group("egg", egg_icon_refs(), copy_texture)
    total += gen_group("egg", eggtype_icon_refs(), crop_sprite)
    print(f"-> {OUT_ROOT}(--force 可强制重编)")
    if total == 0:
        sys.exit(f"未产出任何 webp:确认 {SRC} 下已有 unpack.sh 的全量解包产物。")


if __name__ == "__main__":
    main()
