#!/usr/bin/env python3
"""进化链:按图鉴号归并成「包」,以及按形态间的进化关系分「组」。**全部消费方的进化链口径都出自这里。**

两种粒度,各有各的用处(见 docs/petindex.md):

- **包**(`build`):一个图鉴号一个包,包目录名 `<图鉴号>-<链首名>`。「海盔虫」那种同一只宠物的
  两种外观(两条进化链)归并进同一个包。rocom-pets 的 `data/chains.json`(`--format json`)与
  names.json 里 petbase 的 `cb`(链首图鉴号,rocom-agent 拿它聚合同族)都是它:

      076-海盔虫:包含 海盔虫x2/刺盔虫x2/千棘盔x2/千棘海针 七种形态
                       其中 x2 = 本来的样子/磨损的样子

  没有图鉴号的宠物(未实装居多)一律记 `000`,那一档靠资产名的词干分包。
- **组**(`evolution_groups`):names.json 里 petbase 的 `e`,rocom-capture 详情页按它画整条链
  (分支并列)。比包细:板板壳的两种外观是两个组、一个包;比 PET_EVOLUTION_CONF 粗一点:
  「被污染的星星眼」那批与伊里斯靠 `pet_evolution_id` 挂回本体的组。

数据都来自解包目录(scripts/unpack.sh 产物,`$ROCOM_PARSED`),四张表:

- `PET_EVOLUTION_CONF` —— **进化链的权威表**。`evolution_chain` 是普通形态(带 stage)。
  比顺着 `PETBASE_CONF.evolution_pet_id` 自己爬可靠:那个字段在分支链上是**一串**
  (矿晶虫有 6 个),爬的时候只取第一个就会把另外五条外观整条丢掉。
- `PETBASE_CONF` —— 每个形态的 `pictorial_book_id`(图鉴号,包名前缀)、`stage`、`model_conf`,
  以及**王者形态挂在哪条链上**(`pet_evolution_id`,见 `lords_by_chain`)。
- `MODEL_CONF` —— `model_conf` → 资产目录名(`Wat_HaiKuiChong1Ar_001`)。**判重就靠这个资产名**,
  不是 `model_conf` 自己:同一个王者形态在表里有三四行(千棘海针 4020/5012/8106,
  给图鉴、王者战斗等不同场合各配一行,`model_conf` 各不相同),但指的是同一份模型。
  换外观则是真换资产(`…1_001` vs `…1Ar_001`),所以 x6 那种数量不会被误并。
- `MEGAMAP_CONF` —— 外观标签。`genre` 写成「刺盔虫_本来的样子」,`icon` 就是 petbase_id。

用法(gen.sh --chains <file> 即 `--format json` 的输出;也可单跑):
    uv run python scripts/petindex.py [--format text|tsv|json] [--check]

`--format json` 是 rocom-pets **嵌进客户端与 Worker 的宠物链清单**(它的 `data/chains.json`):
换游戏版本之后在那边重新生成一份提交进仓库。`--check` 是六条样例回归,改了规则先跑它。
"""

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import outdirs

BIN_DIR = Path("NRC/Content/ScriptC/Data/Bin/BinDataCompressed")

CN_NUM = "零一二三四五六七八九十"

# 补过「本来的样子」的形态(见 Form.fill_default_skin);出清单时一并报出来,别让它悄悄混进去
FILLED: list[str] = []
# 靠资产词干认回原包的形态(见 adopt_unbooked);同样要报,那是推断出来的,不是数据直说的
ADOPTED: list[str] = []


def cn_count(n: int) -> str:
    """1 → 「一」,11 → 「十一」,25 → 「二十五」。形态数最多也就二十来个,够用。"""
    if n == 2:
        return "两"  # 「两种形态」,不是「二种形态」;十二仍然念十二,所以只特判这一个
    if n <= 10:
        return CN_NUM[n]
    if n < 20:
        return "十" + CN_NUM[n - 10]
    if n < 100:
        tens, ones = divmod(n, 10)
        return CN_NUM[tens] + "十" + (CN_NUM[ones] if ones else "")
    return str(n)


def rows(parsed: Path, table: str) -> dict:
    path = parsed / BIN_DIR / f"{table}.json"
    if not path.is_file():
        sys.exit(f"缺配置表 {path}\n先跑 scripts/unpack.sh(会把 .bytes 解成 .json),或用 --parsed 指过来")
    return json.loads(path.read_text(encoding="utf-8"))["RocoDataRows"]


def evolution_groups(petbase: dict) -> dict[int, int]:
    """petbase_id → 进化链分组号(组内最小 petbase_id),即 names.json 里 petbase 的 `e`。

    游戏原始的 pet_evolution_id 分组有两个问题:
      ① 分支进化只跟单条路径 —— 果冻→抹茶布丁,漏掉同为二阶的椰浆布丁/熔岩布丁;
      ② 把共享「身份背景」的 NPC 混进链 —— 珂赛特老师(背景=厉毒修萝)、希露德老师(背景=公平鸽),
         以及小游戏变形/剧情/测试/首领(boss)等复制形态,它们与真实图鉴形态同组。
    真实图鉴形态判据 `_real`:有图鉴编号(pictorial_book_id)且 petbase_id 在常规区间(<1e7)。
      * 不能用 legal_petbase==1:传说宠整条链(里奥→灵羽勇士→圣羽翼王、小帕尔→…→龙息帕尔等)
        legal 均为空,会被整条漏掉。
      * 有图鉴号:排除无图鉴的纯 NPC(珂赛特老师/希露德老师/药炉,book=None)。
      * <1e7:排除复制形态 —— 它们虽照抄了图鉴号,但 petbase_id 落在 1.3e7~1.9e7 特殊区间
        (如"迪莫"16000004、"钨丝贝贝(S2剧情骑乘专用)"19000008、"深渊罗隐"13000169);真实形态
        的 petbase_id 都是几千量级。
    对 `_real` 形态按两类无向边求连通分量:evolution_pet_id(该形态可进化成的目标,含全部分支)
      + 原 pet_evolution_id(同组互联,兜底季节地区形态、「被污染的 X」与伊里斯那种第二个一阶)。
    每个含 ≥2 形态的分量即一条完整进化链;单形态(含 boss/特殊形态如"霜翼领主")不入组。

    **比 `build` 的包细**:板板壳的两种外观各一条链、各一个组,包却只有一个(按图鉴号并)。
    包与组的链首图鉴号必须一致,gen_gamedata 生成时核对。
    """
    real = {int(pid) for pid, p in petbase.items()
            if p.get("pictorial_book_id") and int(pid) < 10_000_000}
    adj: dict = {pid: set() for pid in real}
    for pid, p in petbase.items():
        pid = int(pid)
        if pid not in real:
            continue
        for t in p.get("evolution_pet_id") or []:
            if int(t) in real:
                adj[pid].add(int(t))
                adj[int(t)].add(pid)
        ev = p.get("pet_evolution_id")
        if isinstance(ev, list) and ev:
            adj.setdefault(("g", ev[0]), set()).add(pid)  # 用组节点把同组成员连成星形
            adj[pid].add(("g", ev[0]))
    seen: set = set()
    groups: dict[int, int] = {}
    for pid in real:
        if pid in seen:
            continue
        stack, comp = [pid], []
        while stack:  # DFS 连通分量(组节点只作桥,不计入成员)
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            if not isinstance(x, tuple):
                comp.append(x)
            stack.extend(adj[x] - seen)
        if len(comp) >= 2:
            g = min(comp)
            for x in comp:
                groups[x] = g
    return groups


def chain_books(packs: list["Pack"]) -> tuple[dict[int, int], dict[int, int]]:
    """petbase_id → 所在包的图鉴号(链首图鉴号),names.json 里 petbase 的 `cb`。没图鉴号的包(`000`)不给。

    分两份返回:**链上列到的 id** 与 **别名行**(aliases_of:不在链上、模型却是某个已列形态的行,
    如「野外首领雪影娃娃进化链(废弃)」那三行 —— 它们抄的图鉴号 144 是链末雪影娃娃的,模型却是
    142 包的王者雪影冰灵)。后者的图鉴号本来就靠不住,gen_gamedata 只拿前者与分组核对。
    """
    listed, aliased = {}, {}
    for pack in packs:
        if not pack.book:
            continue
        for form in pack.forms.values():
            for ids in form.ids.values():
                for pid in ids:
                    listed[pid] = pack.book
    by_asset = {a: p.book for p in packs if p.book for f in p.forms.values() for a in f.skins}
    for pid, asset in aliases_of(packs).items():
        if asset in by_asset and pid not in listed:
            aliased[pid] = by_asset[asset]
    return listed, aliased


def lords_by_chain(petbase: dict) -> dict[int, list[tuple[int, str]]]:
    """进化链 id → 挂在它上面的王者形态 `[(petbase_id, 名字), …]`,按 id 排。

    **1.111(S4)那版把 `PET_EVOLUTION_CONF.lordevo_chain` 整个删了**,改成王者形态那行
    自己写一个 `pet_evolution_id` 指回链;不认这条的话,叶冕魔力猫/钻石蜗/彩虹独角兽
    那 64 个形态会整批从清单里消失(它们有图鉴号,又进不了 `adopt_unbooked`)。

    认的是 `stage == 4 且 is_boss == 1` —— 全表 67 行,其中 64 行带 `pet_evolution_id`,
    另外 3 行(徽章 BOSS 与领地试炼用)是同一份模型的重复登记,靠资产判重挡掉。
    同一条链可以有两个(喵喵:叶冕魔力猫 5003 与武斗酷猫 5061),id 序正是游戏内的先后。

    新版另有一套 6xxx 的「首领形态」(卡图斯（初级/中级/高级）那 34 行),**不是王者形态**:
    三行一只、共用同一份 `…Bo_001` 模型,只是首领等级不同,名字里那个后缀也跟着变。
    它们没有图鉴号也没有 `pet_evolution_id`,与王者形态撞的是同一份资产 —— 王者形态先占,
    它们就自然落空,清单里因此仍是「钻石蜗」而不是「戴蒙德（初级）」。
    """
    lords: dict[int, list[tuple[int, str]]] = {}
    for key, row in petbase.items():
        try:
            pid = int(key)
        except ValueError:
            continue
        if row.get("stage") != 4 or row.get("is_boss") != 1:
            continue
        for chain_id in row.get("pet_evolution_id") or []:
            lords.setdefault(chain_id, []).append((pid, row.get("name") or str(pid)))
    for members in lords.values():
        members.sort()
    return lords


def skin_labels(megamap: dict) -> dict:
    """petbase_id → 外观标签(「本来的样子」)。`genre` 里下划线前面那截是宠物名,丢掉。"""
    labels = {}
    for row in megamap.values():
        genre, icon = row.get("genre"), row.get("icon")
        if not (genre and icon and "_" in str(genre)):
            continue
        try:
            pid = int(icon)
        except (TypeError, ValueError):
            continue
        labels.setdefault(pid, str(genre).split("_", 1)[1])
    return labels


ASSET_RE = re.compile(r"^([A-Za-z]+_[A-Za-z]+?)(\d+|Bo)(Ar)?_(\d+)$")

#: 人工改名表:`PETBASE_CONF` 那行的名字明显是抄来的,拿别处的实名盖掉。
#: **人工判断,不是数据直说的**:3567(`Mac_LuoDaXie1_001`)的 name 与 icon 都还指着真·落陨星兔
#: (3485,在 335-粉星仔 里),而 NPC_CONF 里这份模型有三行写的是「守护者」。
NAME_OVERRIDES = {3567: "守护者"}


def asset_stem(asset: str) -> str:
    """`Gra_RuoYeXi1_001` → `Gra_RuoYeXi`(一条链共用的那截)。

    资产名的构成是「元素_物种拼音 + 阶段 + 可选 Ar + _变体号」,阶段那位是 `Bo` 就是王者形态。
    没图鉴号的那批在 `evolution_pet_id` 里**一条边都没有**,靠这个词干才能把链重新拼起来
    (design.md §2 早就把「资源目录名数字后缀 = 阶段」列为交叉校验,这里是拿它当主依据)。
    """
    m = ASSET_RE.match(asset)
    return m.group(1) if m else asset


def asset_stage(asset: str) -> int | None:
    """资产名里的阶段位:`Gra_MiaoMiao2_001` → 2,`Gra_MiaoMiaoBo_001` → None(王者形态)。

    **排序优先用它,而不是配置里的 `stage` 字段**:那个字段是**相对本条链**的,
    半路起头的链会从 1 开始数(路路尼那条链只有它一个,写着 stage 1,可它明明是二阶),
    于是把散落的成员认回来之后,顺序就乱了。资产名里的数字是绝对的。
    """
    m = ASSET_RE.match(asset)
    if not m or m.group(2) == "Bo":
        return None
    return int(m.group(2))


def is_lord_asset(asset: str) -> bool:
    m = ASSET_RE.match(asset)
    return bool(m) and m.group(2) == "Bo"


def chain_label(chain_name: str) -> str | None:
    """「矿晶虫进化链(西瓜碧玺的样子)」→「西瓜碧玺的样子」。没括号就没有。

    **「…分支」不算外观**:果冻那三条链叫「果冻进化链(抹茶布丁分支)」,说的是分支去向、
    不是长相 —— 当外观标签用会写出「x3 表示有 抹茶布丁分支/…」这种莫名其妙的话。
    """
    left = chain_name.find("（")
    if left < 0 or not chain_name.rstrip().endswith("）"):
        return None
    label = chain_name[left + 1 : chain_name.rstrip().rfind("）")]
    return None if label.endswith("分支") else label or None


class Form:
    """归并之后的一个形态:一个名字 + 若干种外观(每种外观一个 model_conf)。"""

    def __init__(self, name: str, stage: int, lord: bool):
        self.name = name
        self.stage = stage
        self.lord = lord
        # 资产名 → 外观标签(可能为 None);**用资产名判重**,见模块头
        self.skins = OrderedDict()
        # 资产名 → 链上指着它的宠物 id。`--format json` 要:外部按宠物 id 找包
        self.ids: OrderedDict[str, list[int]] = OrderedDict()

    def add(self, asset: str, label: str | None, pid: int) -> None:
        self.skins.setdefault(asset, label)
        ids = self.ids.setdefault(asset, [])
        if pid not in ids:
            ids.append(pid)

    @property
    def count(self) -> int:
        return len(self.skins)

    def fill_default_skin(self) -> bool:
        """基础那一版没名字时补上「本来的样子」,返回补没补。

        游戏只给「特殊的那一版」登记名字:波波螺有「被污染的样子」,原样反而没条目。
        **这四个字是我们补的、数据里没有** —— 但它正是游戏自己在肯登记时用的说法
        (板板壳_本来的样子、冬羽雀_本来的样子),不是另造一套词。
        只补**孤零零一个**没名字的:两个都没名字就说明这不是「基础版 + 特殊版」那种结构,
        瞎补会把话说错。
        """
        blank = [model for model, label in self.skins.items() if not label]
        if self.count < 2 or len(blank) != 1:
            return False
        self.skins[blank[0]] = "本来的样子"
        return True

    def render(self) -> str:
        return f"{self.name}x{self.count}" if self.count > 1 else self.name

    def skin_note(self) -> str | None:
        """有多种外观、且标签齐全时,给一句「x2 表示有 …/… 两种外观」。

        标签缺一个就整条不给:「x3 表示有 A/B」比不解释更让人犯嘀咕。
        """
        if self.count < 2:
            return None
        labels = [lab for lab in self.skins.values() if lab]
        if len(labels) != self.count:
            return None
        note = f"x{self.count} 表示有 " + "/".join(labels)
        return note + " 两种外观" if self.count == 2 else note


class Pack:
    """一个图鉴号 = 一个包。**没有图鉴号的一律记 `000`**,那一档靠资产词干彼此分开
    (见 `build` 里 key2 的说明),所以 `000` 上会挂着好几十个包。"""

    def __init__(self, book: int, name: str):
        self.book = book
        self.name = name
        self.forms: OrderedDict[str, Form] = OrderedDict()
        self.chains: list[int] = []
        # 资产名 → 收进来的先后。`--format json` 里形态按 (王者, 阶段, 先后) 排,
        # 与导出器 Finish() 写进 manifest 的顺序一致
        self.seq: dict[str, int] = {}

    def take(self, form: "Form", asset: str, label: str | None, pid: int) -> None:
        form.add(asset, label, pid)
        self.seq.setdefault(asset, len(self.seq))

    @property
    def file_name(self) -> str:
        return f"{self.book:03d}-{self.name}"

    def ordered(self) -> list[Form]:
        # 普通形态按 stage,王者形态一律排最后(它们的 stage 是 4,但同为 4 的普通形态
        # 也有,排序键里显式分开更稳)
        return sorted(self.forms.values(), key=lambda f: (f.lord, f.stage))

    @property
    def total(self) -> int:
        return sum(f.count for f in self.ordered())


def build(parsed: Path) -> list[Pack]:
    petbase = rows(parsed, "PETBASE_CONF")
    evolution = rows(parsed, "PET_EVOLUTION_CONF")
    model_conf = rows(parsed, "MODEL_CONF")
    labels = skin_labels(rows(parsed, "MEGAMAP_CONF"))
    lords = lords_by_chain(petbase)

    def base(pid: int) -> dict:
        return petbase.get(str(pid)) or {}

    def asset_of(pid: int) -> str:
        """这个形态用哪份模型资产。**认不出就返回空串** —— 那种行不该进清单。

        `MODEL_CONF.path` 里没有 `/Pets/…` 的只有四行(幸运惊喜盒 ×3、随机精灵),
        是界面上的占位条目,不是宠物;没有资产目录也就无从导出。
        """
        model = base(pid).get("model_conf")
        path = (model_conf.get(str(model)) or {}).get("path") or ""
        _, _, rest = path.partition("/Pets/")
        return rest.split("/", 1)[0] if rest else ""

    packs: dict[tuple[int, str], Pack] = {}
    # 有图鉴号的先来:它们说了算。**没图鉴号的那批里有一堆借着别人的模型占位** ——
    # `Com_YaJiJi1_001` 是鸭吉吉的模型,却被 53 个还没做模型的宠物拿去顶着,
    # 不先把有主的资产占掉,那 53 个会连成一个二十几形态的怪包
    taken: set[str] = set()
    ordered_chains = sorted(
        ((int(k), v) for k, v in evolution.items()),
        key=lambda kv: (
            base(((kv[1].get("evolution_chain") or [{}])[0]).get("petbase_id", 0)).get(
                "pictorial_book_id"
            )
            is None,
            kv[0],
        ),
    )
    # 有图鉴号的包占着哪些资产。**判断某个没图鉴号的链首是不是在「顶别人的模型」就靠它**
    booked_assets = {
        asset_of(m["petbase_id"])
        for _, chain in ordered_chains
        for m in (chain.get("evolution_chain") or [])
        if base((chain["evolution_chain"] or [{}])[0].get("petbase_id", 0)).get(
            "pictorial_book_id"
        )
        is not None
    }
    for key, chain in ordered_chains:
        members = chain.get("evolution_chain") or []
        # 链名自己写着「废弃」的不要(两条:野外首领梦想三三/雪影娃娃)。
        # 它们仨成员指的是同一份 BOSS 模型,收进来会白白多出两个只有一份模型的包
        if not members or any(m in (chain.get("name") or "") for m in ("废弃", "占位", "测试")):
            continue
        root = members[0]
        book = base(root["petbase_id"]).get("pictorial_book_id")
        # 键是 (图鉴号, 次序) —— 没图鉴号的那批都排在 0 号,靠资产词干彼此分开。
        # **链首没图鉴号也照收**:那条链在 PET_EVOLUTION_CONF 里是全的(连王者形态一起),
        # 比后面 adopt_unbooked 靠词干拼出来的强;词干当键,好让散落的成员认回同一个包
        # 没图鉴号的用**链首资产的词干**分包:同根的几条分支链(菌宝那四条)并成一个,
        # 换外观的几条(雪毛角羚牛那三条,`…1_001` / `…1Ar_001` / `…1Ar_002`)也并成一个 ——
        # 有图鉴号的那批靠图鉴号并,这批只剩词干可用。
        # **链首顶着别人的模型时不能用词干**:五条毫不相干的链都指着鸭吉吉的
        # `Com_YaJiJi1_001`,按词干会并成一个二十几形态的怪包;那时退回按链首 id 各归各的
        root_asset = asset_of(root["petbase_id"])
        key2 = ""
        if book is None:
            own = root_asset and root_asset not in booked_assets
            key2 = asset_stem(root_asset) if own else f"pet{root['petbase_id']}"
        pack = packs.setdefault((book or 0, key2), Pack(book or 0, root["pet_name"]))
        pack.chains.append(key)
        # 链名自己就带着外观:「矿晶虫进化链(西瓜碧玺的样子)」。**当 MEGAMAP 的补漏**——
        # 那张表只登记了「特殊的那一版」,基础版往往没有条目(脆筒甜甜的樱桃巧克力口味
        # 就只在链名里);而链名对整条链有效,正好补上
        chain_skin = chain_label(chain.get("name") or "")

        listed = [(m["petbase_id"], m["pet_name"], m.get("stage", 0), False) for m in members]
        listed += [
            (pid, pet_name, base(pid).get("stage", 4), True)
            for pid, pet_name in lords.get(key, [])
        ]
        for pid, pet_name, stage, lord in listed:
            pet_name = NAME_OVERRIDES.get(pid, pet_name)
            asset = asset_of(pid)
            if not asset:
                continue
            # 没图鉴号的不许抢已经有主的资产(见上面 taken 的说明);
            # 有图鉴号的照收 —— 同一份模型在几个包里各占一格是正常的(千棘海针那种)
            if book is None and asset in taken:
                continue
            taken.add(asset)
            form = pack.forms.get(pet_name)
            if form is None:
                # 王者形态不套资产阶段位:它们的资产名写的是 `…Bo_001`(没有数字),
                # 认不出就会退回配置里的 stage,而同一条链的几个王者 stage 全一样 ——
                # 那时候该保持 `lordevo_chain` 里的先后(叶冕魔力猫在武斗酷猫前面)
                form = pack.forms[pet_name] = Form(
                    pet_name, stage if lord else (asset_stage(asset) or stage), lord
                )
            # **同名同资产 = 同一个形态**:钻石蜗在六条链里各挂一个 id,
            # 指的都是 Lig_KuangChongBo_001,只该算一种
            pack.take(form, asset, labels.get(pid) or chain_skin, pid)

    # 整条链的形态都被上面那条规则挡掉的话,包就空了 —— 别留个没形态的壳
    for k in [k for k, p in packs.items() if not p.forms]:
        del packs[k]
    adopt_unbooked(packs, petbase, asset_of, labels)

    result = list(packs.values())
    for pack in result:
        # 链首被挡掉时(它顶着别人的模型),包名得改成留下来的头一环 ——
        # 不然会出现一个叫「呆火鸟」、里面根本没有呆火鸟的包
        if pack.name not in pack.forms:
            pack.name = pack.ordered()[0].name
        for form in pack.forms.values():
            if form.fill_default_skin():
                FILLED.append(f"{pack.file_name} 的 {form.name}")
    # **排序放在改名之后**:`000` 那一档的包名要等收养完才定下来。图鉴号,然后按名字的码位序
    result.sort(key=lambda p: (p.book, p.name))
    # 给 as_json 用:不在任何链上、模型却是某个形态那份资产的行(见 aliases_of)
    build.petbase, build.asset_of = petbase, asset_of
    return result


def unbooked_rows(petbase: dict, taken: set[str], asset_of) -> list[tuple[int, dict, str]]:
    """没有图鉴号、资产也还没被收走的那些行。

    过滤掉三类:`首领-xxx`(BOSS 行,和本体同一份模型)、名字带「占位」的(数据自己说的)、
    以及 `legal_petbase == 0`(明确作废)。**id 不在 1000~99999 的**是影子行,也不要。
    """
    out = []
    for key, row in petbase.items():
        try:
            pid = int(key)
        except ValueError:
            continue
        name = row.get("name") or ""
        if not (1000 <= pid <= 99999) or not name:
            continue
        if any(mark in name for mark in ("测试", "Test", "占位")) or name.startswith("首领"):
            continue
        if row.get("legal_petbase") == 0 or row.get("pictorial_book_id") is not None:
            continue
        asset = asset_of(pid)
        if not asset or asset in taken:
            continue
        out.append((pid, row, asset))
    return out


def adopt_unbooked(packs: dict, petbase: dict, asset_of, labels: dict) -> None:
    """把没图鉴号的形态收进来:词干对得上的并进原包,剩下的自成 `000-xxx`。

    **词干对得上就不是新宠物**,是原包缺的那一环 —— 实测八处:赤毛鸡仔那条链缺三阶
    (伊丽莎白 `Fir_JiZai3_001`)、路路尼缺一阶和三阶、小鼠獭缺王者(卷发巨獭 `…ShuTaBo_001`)
    等等。丢进 000 会把一条链劈成两个包,正好和「规范化合并」反着来。
    """
    taken = {a for p in packs.values() for f in p.forms.values() for a in f.skins}
    by_stem = {
        asset_stem(a): pack
        for pack in packs.values()
        for f in pack.forms.values()
        for a in f.skins
    }
    orphans: dict[str, Pack] = {}
    for pid, row, asset in sorted(unbooked_rows(petbase, taken, asset_of)):
        if asset in taken:
            continue  # 同一份模型挂着好几行(古路尼 3365/8024),头一行说了算
        taken.add(asset)
        name = NAME_OVERRIDES.get(pid) or row.get("name") or str(pid)
        lord = is_lord_asset(asset)
        stage = row.get("stage") or 0 if lord else (asset_stage(asset) or row.get("stage") or 0)
        stem = asset_stem(asset)
        home = by_stem.get(stem)
        if home is not None:
            ADOPTED.append(f"{home.file_name} ← {name}({asset})")
        else:
            # 000 里同一条链的成员靠词干聚在一起(它们的 evolution_pet_id 是空的)
            home = orphans.get(stem)
            if home is None:
                home = orphans[stem] = Pack(0, name)
                packs[(0, stem)] = home
        # 包名跟着最靠前的那一环走:路路尼(二阶)收进 路路(一阶)之后该改叫 路路。
        # **要在挂进去之前比**,不然拿自己和自己比,永远不会更靠前
        earlier = min((f.stage for f in home.forms.values() if not f.lord), default=99)
        if not lord and stage < earlier:
            home.name = name
        form = home.forms.get(name)
        if form is None:
            form = home.forms[name] = Form(name, stage, lord)
        home.take(form, asset, labels.get(pid), pid)


def notes_of(forms: list[Form]) -> list[str]:
    """一个包里的外观说明。

    **同一套外观说一遍就够**:一条链上每一环往往共用同一组外观(海盔虫/刺盔虫/千棘盔
    都是「本来的/磨损的」),逐个形态各说一句是三份一模一样的话。
    去重之后要是还剩不止一条(一个包里几个形态各有各的外观),就把形态名带上,
    否则光看「x2 表示有…」不知道说的是哪一个。
    """
    seen = OrderedDict()
    for form in forms:
        if note := form.skin_note():
            seen.setdefault(note, []).append(form.name)
    if len(seen) <= 1:
        return list(seen)
    return [f"{names[0]} 的 {note}" for note, names in seen.items()]


def as_text(packs: list[Pack]) -> str:
    out = []
    for pack in packs:
        forms = pack.ordered()
        line = (
            f"{pack.file_name}:包含 "
            + "/".join(f.render() for f in forms)
            + f" {cn_count(pack.total)}种形态"
        )
        if notes := notes_of(forms):
            line += ",其中 " + ";".join(notes)
        out.append(line + ";")
    return "\n".join(out)


def aliases_of(packs: list[Pack]) -> dict[int, str]:
    """宠物 id → 资产名:表里指着某个已列形态的模型、自己却不在链上的那些行。

    同一个王者形态在表里有三四行(千棘海针 4020/5012/8106,给图鉴、王者战斗等场合各配一行),
    抓包里看到的 `base_conf_id` 可能是其中任一行;客户端按 id 找包时靠这张表认回去。
    只收 `IsExportable` 那一档的行(1000~99999、有名字、不是测试/占位/首领)。
    """
    listed = {pid for p in packs for f in p.forms.values() for ids in f.ids.values() for pid in ids}
    assets = {a for p in packs for f in p.forms.values() for a in f.skins}
    out = {}
    for key, row in build.petbase.items():
        try:
            pid = int(key)
        except ValueError:
            continue
        name = row.get("name") or ""
        if not (1000 <= pid <= 99999) or not name or pid in listed:
            continue
        if any(mark in name for mark in ("测试", "Test", "占位")) or name.startswith("首领"):
            continue
        asset = build.asset_of(pid)
        if asset in assets:
            out[pid] = asset
    return dict(sorted(out.items()))


def as_json(packs: list[Pack], petbase: dict) -> str:
    """`types` 是系别(`PETBASE_CONF.unit_type`,`TYPE_DICTIONARY` 的行号;双系两个,主系在前)。
    **不能从资产前缀推**:莫比乌乌 / 克莱因龙的资产是 `Ill_`(幻),表里却是龙系,
    实机盒子给它们的也是龙系的红底。客户端拿它选预览背景色(src/catalog.rs `Element`)。"""
    chains = []
    for pack in packs:
        rows = sorted(
            ((form, asset) for form in pack.forms.values() for asset in form.skins),
            key=lambda fa: (fa[0].lord, fa[0].stage, pack.seq[fa[1]]),
        )
        forms = []
        for form, asset in rows:
            # 同名的多种外观带外观后缀,与导出器 Finish() 的写法一致;缺标签的退用资产名
            label = form.skins[asset]
            ids = form.ids[asset]
            forms.append({
                "name": f"{form.name}({label or asset})" if form.count > 1 else form.name,
                "asset": asset, "stage": form.stage, "lord": form.lord,
                "ids": ids,
                "types": petbase.get(str(ids[0]), {}).get("unit_type") or [],
                # 这个形态自己的图鉴号(链上每个形态各有一号,包名只用链首那个);搜索要认全部
                "book": petbase.get(str(ids[0]), {}).get("pictorial_book_id") or 0,
            })
        chains.append({"book": pack.book, "dir": pack.file_name, "name": pack.name, "forms": forms})
    return json.dumps({"chains": chains, "aliases": aliases_of(packs)}, ensure_ascii=False, indent=1)


def as_tsv(packs: list[Pack]) -> str:
    out = ["图鉴号\t包名\t形态数\t形态构成\t进化链 id"]
    for pack in packs:
        out.append(
            "\t".join(
                [
                    f"{pack.book:03d}",
                    pack.file_name,
                    str(pack.total),
                    "/".join(f.render() for f in pack.ordered()),
                    ",".join(str(c) for c in pack.chains),
                ]
            )
        )
    return "\n".join(out)


# 六条样例当回归基线(rocom-pets 早期人工核对过的)
EXPECTED = {
    2: ("002-喵喵", "喵喵/喵呜/魔力猫/叶冕魔力猫/武斗酷猫", 5),
    39: ("039-矿晶虫", "矿晶虫/晶石蜗x6/钻石蜗", 8),
    76: ("076-海盔虫", "海盔虫x2/刺盔虫x2/千棘盔x2/千棘海针", 7),
    116: ("116-小独角兽", "小独角兽/白金独角兽/彩虹独角兽", 3),
    313: ("313-果冻", "果冻/抹茶布丁/椰浆布丁/熔岩布丁", 4),
    322: ("322-月牙雪熊", "月牙雪熊", 1),
}


def check(packs: list[Pack]) -> int:
    by_book = {p.book: p for p in packs}
    bad = 0
    for book, (file_name, forms, total) in EXPECTED.items():
        pack = by_book.get(book)
        got = (
            (pack.file_name, "/".join(f.render() for f in pack.ordered()), pack.total)
            if pack
            else None
        )
        if got == (file_name, forms, total):
            print(f"  ok  {file_name}")
        else:
            bad += 1
            print(f"  ✗   期望 {(file_name, forms, total)}\n      实得 {got}")
    print(f"\n{len(EXPECTED) - bad}/{len(EXPECTED)} 条样例对上了")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parsed", type=Path, default=Path(outdirs.PARSED),
                    help="解包根(默认 $ROCOM_PARSED,再默认 ~/Downloads/rocom/parsed)")
    ap.add_argument("--format", choices=["text", "tsv", "json"], default="text")
    ap.add_argument("--check", action="store_true", help="只跑样例回归,不出清单")
    args = ap.parse_args()

    packs = build(args.parsed)
    # 包目录名是消费方的键(rocom-pets 按它找资产),撞了号已经不解决问题,得改规则
    from collections import Counter
    for name, n in Counter(p.file_name for p in packs).items():
        if n > 1:
            print(f"!! 包名 {name} 被 {n} 个包共用", file=sys.stderr)
    if args.check:
        return 1 if check(packs) else 0

    if args.format == "json":
        print(as_json(packs, rows(args.parsed, "PETBASE_CONF")))
        return 0
    print(as_text(packs) if args.format == "text" else as_tsv(packs))
    print(
        f"\n# {len(packs)} 个包 / {sum(p.total for p in packs)} 个形态"
        f"(含外观变体);归并前是 {sum(len(p.chains) for p in packs)} 条进化链",
        file=sys.stderr,
    )
    if FILLED:
        print(
            f"# 有 {len(FILLED)} 个形态的基础外观在数据里没名字,按惯例补了「本来的样子」:"
            + "、".join(FILLED),
            file=sys.stderr,
        )
    if ADOPTED:
        print(
            f"# 有 {len(ADOPTED)} 个没图鉴号的形态**按资产词干认回了原包**(推断,不是数据直说的):"
            + "、".join(ADOPTED),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
