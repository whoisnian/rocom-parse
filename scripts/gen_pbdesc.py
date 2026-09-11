"""生成 pcapdump 精确解码所需的描述符集,输出到 $ROCOM_PBDESC_OUT(默认 build/pbdesc,见 outdirs.py)。

pcapdump 的「通用 wire 级」解码(不依赖 .proto)字段只有编号、嵌套还可能切错。
本脚本把游戏描述符 all.pb 精简成「opcode 能用到的那部分」,让 pcapdump 按真实字段名/枚举名解码:

- proto.desc.gz: FileDescriptorSet(gzip)。只保留从 opcode 对应消息可达的消息/枚举
                 (3000+/3800 消息、170/1000+ 枚举),丢弃 service、扩展与无关类型。
- opmsg.json:    opcode 整数 -> 消息全名(如 786 -> ".Next.ZoneGetAllHatchStatusRsp")。
                 映射表在客户端 ProtoCMD.lua 里(`[ProtoCMD.ZoneSvrCmd.X] = ".Next.Y"`),
                 opcode 数值取 all.pb 的 ZoneSvrCmd/ZoneSvrGmCmd 枚举,两者对得上才收。
- opname.json:   opcode 整数 -> ZoneSvrCmd 枚举名(如 258 -> "ZONE_LOGIN_RSP"),全集,
                 含没有消息映射的 opcode;pcapdump 概览按它显示名称。

运行(需 uv 管理的 protobuf 依赖):  uv run python scripts/gen_pbdesc.py
更新游戏版本:重跑 scripts/unpack.sh 刷新解包目录再跑本脚本(解包根用 ROCOM_PARSED 覆盖)。
"""
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import outdirs
import pbdesc

from google.protobuf import descriptor_pb2 as dpb

PB_DIR = os.path.join(outdirs.PARSED, "NRC", "Content", "ScriptC", "Data", "PB")
ALL_PB = os.path.join(PB_DIR, "all.pb")
PROTO_CMD = os.path.join(PB_DIR, "ProtoCMD.lua")
OUT = outdirs.PBDESC_OUT
# ProtoCMD.lua 里 opcode -> 消息名的映射行,形如:
#   [ProtoCMD.ZoneSvrCmd.ZONE_LOGIN_REQ] = ".Next.ZoneLoginReq",
CMD_LINE = re.compile(r"\[ProtoCMD\.(\w+)\.(\w+)\]\s*=\s*\"([\w.]+)\"")
# 取 opcode 数值的枚举(后者优先级低,冲突时不覆盖)
CMD_ENUMS = ["ZoneSvrCmd", "ZoneSvrGmCmd"]


def index_types(fds):
    """建立 {消息全名: (文件名, DescriptorProto)} 与 {枚举全名: 文件名}。"""
    msgs, enums = {}, {}

    def walk(f, prefix, m):
        full = prefix + "." + m.name
        msgs[full] = (f.name, m)
        for e in m.enum_type:
            enums[full + "." + e.name] = f.name
        for n in m.nested_type:
            walk(f, full, n)

    for f in fds.file:
        prefix = "." + f.package if f.package else ""
        for m in f.message_type:
            walk(f, prefix, m)
        for e in f.enum_type:
            enums[prefix + "." + e.name] = f.name
    return msgs, enums


def opcode_map(fds):
    """解析 ProtoCMD.lua,返回 {opcode 整数: 消息全名}。"""
    if not os.path.exists(PROTO_CMD):
        sys.exit(f"缺 {PROTO_CMD}(unpack.sh 反编译 ProtoCMD.luac 得到)")
    with open(PROTO_CMD, encoding="utf-8") as f:
        text = f.read()
    values = {}   # 枚举名 -> {值名: 整数}
    for name in CMD_ENUMS:
        values[name] = pbdesc.enum(fds, name)
    out, miss = {}, 0
    for enum_name, value_name, msg in CMD_LINE.findall(text):
        num = values.get(enum_name, {}).get(value_name)
        if num is None:
            miss += 1
            continue
        full = msg if msg.startswith(".") else "." + msg
        out.setdefault(num, full)
    if miss:
        print(f"  跳过 {miss} 条(枚举值不在 all.pb 的 {'/'.join(CMD_ENUMS)} 里)")
    return out


def reachable(msgs, enums, roots):
    """从 roots(消息全名)出发,收集字段可达的消息与枚举全名。

    第三个返回值 keep_shell 是「只作为容器保留」的外层消息:被引用的枚举/消息可能嵌套在
    某个自身用不到的消息里(如 .Next.PlayerOnlineState.ENUM),外层不留下空壳就解析不到。
    """
    keep_m, keep_e, missing = set(), set(), set()

    def visit(name):
        if name in keep_m:
            return
        if name not in msgs:
            missing.add(name)
            return
        keep_m.add(name)
        for fd in msgs[name][1].field:
            t = fd.type_name
            if not t:
                continue
            if t in msgs:
                visit(t)
            elif t in enums:
                keep_e.add(t)

    for r in roots:
        visit(r)

    keep_shell = set()
    for name in list(keep_m) + list(keep_e):
        parts = name.split(".")
        for i in range(len(parts) - 1, 0, -1):
            outer = ".".join(parts[:i])
            if outer in msgs and outer not in keep_m:
                keep_shell.add(outer)
    return keep_m, keep_e, keep_shell, missing


def prune(fds, keep_m, keep_e, keep_shell):
    """按 keep 集裁剪描述符:丢 service/扩展/无关消息与枚举,依赖表同步收紧。"""
    kept_files = set()
    out = dpb.FileDescriptorSet()
    for f in fds.file:
        prefix = "." + f.package if f.package else ""
        nf = dpb.FileDescriptorProto()
        nf.CopyFrom(f)
        del nf.service[:]      # service 引用的消息可能已被裁掉
        del nf.extension[:]    # 自定义 option 扩展(rpc_options)对解码无用
        del nf.message_type[:]
        del nf.enum_type[:]

        def copy_msg(m, parent, dst):
            full = parent + "." + m.name
            if full not in keep_m and full not in keep_shell:
                return
            d = dst.add()
            d.CopyFrom(m)
            del d.nested_type[:]
            del d.enum_type[:]
            del d.extension[:]
            if full not in keep_m:   # 空壳:只为承载内层被引用的枚举/消息
                del d.field[:]
                del d.oneof_decl[:]
            for n in m.nested_type:
                copy_msg(n, full, d.nested_type)
            for e in m.enum_type:
                if full + "." + e.name in keep_e:
                    d.enum_type.add().CopyFrom(e)

        for m in f.message_type:
            copy_msg(m, prefix, nf.message_type)
        for e in f.enum_type:
            if prefix + "." + e.name in keep_e:
                nf.enum_type.add().CopyFrom(e)
        if not nf.message_type and not nf.enum_type:
            continue
        kept_files.add(f.name)
        out.file.append(nf)
    # 依赖只留仍在集合里的文件(被引用类型所在文件必然保留,故不会丢引用);
    # public/weak 依赖是下标,裁剪后失配,直接清掉。
    for f in out.file:
        deps = [d for d in f.dependency if d in kept_files]
        del f.dependency[:]
        f.dependency.extend(deps)
        del f.public_dependency[:]
        del f.weak_dependency[:]
    return out


def main():
    fds = pbdesc.load(ALL_PB)
    msgs, enums = index_types(fds)
    ops = opcode_map(fds)
    print(f"opcode 映射: {len(ops)} 条")

    keep_m, keep_e, keep_shell, missing = reachable(msgs, enums, set(ops.values()))
    if missing:
        print(f"  {len(missing)} 个消息名在 all.pb 里不存在(ProtoCMD.lua 领先于描述符),已忽略")
        ops = {op: m for op, m in ops.items() if m not in missing}
    print(f"保留消息 {len(keep_m)}(+{len(keep_shell)} 空壳)/{len(msgs)}, 枚举 {len(keep_e)}/{len(enums)}")

    pruned = prune(fds, keep_m, keep_e, keep_shell)
    raw = pruned.SerializeToString()
    # mtime=0:gzip 头默认写当前时间,会让内容没变的重跑也产出不同字节(git 噪音)
    blob = gzip.compress(raw, 9, mtime=0)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "proto.desc.gz"), "wb") as f:
        f.write(blob)
    with open(os.path.join(OUT, "opmsg.json"), "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in sorted(ops.items())}, f,
                  ensure_ascii=False, separators=(",", ":"))
    # ZoneSvrCmd 全集的枚举名:pcapdump 概览/过滤按名称用,与 opmsg 无关的 opcode 也要有名
    opnames = {str(v): k for k, v in sorted(pbdesc.enum(fds, "ZoneSvrCmd").items(), key=lambda kv: kv[1])}
    with open(os.path.join(OUT, "opname.json"), "w", encoding="utf-8") as f:
        json.dump(opnames, f, ensure_ascii=False, separators=(",", ":"))
    print(f"-> {OUT}/proto.desc.gz  ({len(pruned.file)} 文件, {len(raw)}B -> gz {len(blob)}B)")
    print(f"-> {OUT}/opmsg.json     ({len(ops)} 条)")
    print(f"-> {OUT}/opname.json    ({len(opnames)} 条)")


if __name__ == "__main__":
    main()
