# 协议说明：tsf4g / GCP

游戏客户端通过 TCP 连接远端服务器 **8195** 端口，使用腾讯 tsf4g 框架的 GCP 模式通信。
本文记录经真实流量逐字节验证的线上格式，是本仓库 `gcp` 与 `capture` 包的实现依据(游戏消息层的字段解析在 rocom-capture 的 docs/protocol.md)。

> 概念性说明参见 tsf4g 文档(见 [reference.md](reference.md))。本文只记录**实测**结论。

## 1. 分层结构

```
TCP 流(需重组)
  └─ GCP 包(可跨多个 TCP 段，也可能一个段含多个包)
       ├─ HEAD.base  定长 21 字节，明文
       ├─ HEAD.extend 变长，明文(本项目不解析)
       └─ BODY        变长，DATA 包为 AES 密文
```

一个 GCP 包的总长度 = `hdr_len + body_len`，二者都在 HEAD.base 里。
因此接收方必须先 TCP 重组成连续字节流，再按 `magic` 同步、按长度切包。

## 2. HEAD.base 字节布局(定长 21 字节，多字节大端)

| 偏移 | 字段 | 类型 | 说明 |
| --- | --- | --- | --- |
| 0–1 | magic | u16 BE | 固定 `0x3366`，每个包头都有，用于流内同步 |
| 2–3 | head_version | u16 BE | 实测 `0x000b` |
| 4–5 | body_version | u16 BE | 实测 `0x000b` |
| 6–7 | command | u16 BE | 包类型，见下表 |
| 8 | flag | u8 | 方向/加密标志：上行 `0x00`，下行 `0x01` |
| 9–12 | sequence | u32 BE | 序列号，上行/下行各自独立递增 |
| 13–16 | hdr_len | u32 BE | HEAD 总长度(含 extend) |
| 17–20 | body_len | u32 BE | BODY 长度 |

`HEAD.extend = [21, hdr_len)`，`BODY = [hdr_len, hdr_len + body_len)`。

### command 类型(部分)

| 值 | 名称 | 方向 | 说明 |
| --- | --- | --- | --- |
| `0x1001` | SYN | 上行 | 握手 |
| `0x1002` | ACK | 下行 | **明文下发 16 字节会话密钥** |
| `0x2001/0x2002` | AUTH_REQ/RSP | 双向 | 鉴权 |
| `0x6002` | BINGO | 下行 | 连接就绪 |
| `0x4013` | DATA | 双向 | 应用数据，BODY 为密文 |
| `0x9001` | HEARTBEAT | 双向 | 心跳 |
| `0x5002` | SSTOP | 下行 | 服务端断开 |

## 3. 密钥与解密

本游戏采用**服务器明文下发密钥**(非 DH 交换)：

- `0x1002 ACK` 包的 `HEAD.extend[2:18]` 即 16 字节 AES-128 会话密钥(每次连接不同)。
- `0x4013 DATA` 的 BODY 用 **AES-CBC** 解密，两种模式：
  - `embedded_iv`：`BODY[:16]` 为 IV，`BODY[16:]` 为密文；
  - `fixed_iv`：整个 BODY 为密文，IV 固定(全零)。

> 必须先抓到该连接的 ACK 才能解密其后的 DATA。若从连接中途开始抓包则无密钥。

## 4. 应用层 internal header(解密后明文)

DATA 解密后是应用层消息，前缀一个 internal header，**上下行格式不同**：

```
c2s(上行)：  [0:6]?  [6:8] opcode(BE u16)  [8:] ...        body 从约 8 偏移起
s2c(下行)：  [0:2]?  [2:4] opcode(BE u16)  [4:6]=0x55aa  [6:10] seq  [10:] protobuf body
```

- **opcode** 是应用层命令号，对应 `ZoneSvrCmd` 枚举(如 `257=ZONE_LOGIN_REQ`、
  `4934=ZONE_GET_PET_INFO_BY_PAGE_RSP`)。名称表见 [data.md](data.md)。
- s2c 的 protobuf body 从偏移 10 开始(剥离 `0x55aa` 与 seq)。

实测命中率：c2s opcode@6 ≈ 99%，s2c opcode@2 = 100%。

**c2s protobuf body 与 trailer**(实测 `ZONE_SCENE_MOVE_REQ` 0x0133,rocom-capture 的 `internal/scene` 依此解析)：
opcode 之后还有 **6 字节子头**(前 2 字节随包变化、余 4 字节为 0),故 protobuf 从偏移 `8+6=14`
起(`gcp.AppBody` 只剥到 8,子头留在 AppBody 头 6 字节)。protobuf **之后、`tsf4g` 尾之前**还有
一段**变长 trailer**(路由/校验),长度不定。因此解析 c2s body 不能要求「消费到 tsf4g」,应
**贪婪解析已知字段、遇到不属于该消息的字段即停**(trailer 起始处 wire type/字段号必然不符)。
注:c2s 字段**不保证按字段号升序**(实测 move 包顺序为 1,4,7,2,15,3,6,8,5,17)。


## 5. TCP 重组与会话(`capture` 包)

- **方向判定**:`reassembly` 每个 TCP 连接只创建一个 `Stream`,双向数据经同一
  `ReassembledSG`,用 `sg.Info()` 的方向 + 触发包端口映射为 c2s/s2c。
- **flush 用抓包时钟(实时中段接入必需)**:`reassembly` 在中段接入(未见 SYN)时会把起始
  数据当作"等待更早分段"缓冲,须 flush 才下推。`Process()` 每 `flushEvery` 包调一次
  `FlushWithOptions{T: lastTS-flushLag, TC: lastTS-closeIdle}`,阈值取**最新包时间戳**
  `lastTS` 而非墙钟——实时流里墙钟-2min 永远追不上活跃连接的数据时间,起始 backlog 会一直
  卡住直到 EOF 的 `FlushAll`(而 `Ctrl-C` 会跳过它),表现为"重启后能恢复密钥却收不到任何
  消息"。`T` 促使跨间隙滞留数据近实时下推,`TC` 只关闭真正空闲的连接、不误关活跃连接。
- **会话密钥共享**:c2s/s2c 两个半连接归一化为同一 `session`,ACK(下行)提取的密钥
  供同会话的 DATA 解密。
- **会话密钥持久化(重启续解)**:密钥仅在连接建立时的 `0x1002 ACK` 明文下发一次;抓包
  服务若在密钥协商之后才启动/重启,拿不到密钥则整条连接的 DATA 全被当无密钥丢弃。
  为此 `Engine.Keys`(可选 `KeyStore` 接口,由消费方实现落库)把 `connID→密钥` 持久化:
  连接首次出现时预热密钥、收到 ACK 时落盘。因 AES-CBC 每个 DATA 包自带 IV(或固定零 IV)、
  解密无跨包状态,只要密钥在手,重启后从流中段接上的 DATA 即可独立解密。**防误用**:四元组被
  新连接复用时可能套到陈旧缓存密钥,故解密后用 `gcp.ValidPlain` 校验 s2c 明文固定标记
  `0x55aa`,不符即丢弃(新连接的 ACK 会重下发正确密钥覆盖);缓存过期由消费方兜底。
- **多份轮转 pcap 当一条流读**(`RunOfflineFiles`):会话密钥只在第一份的 ACK 里,汇编器与
  会话表跨文件保留、只在最后 FlushAll;文件边界上丢掉的跨界分段靠 `gcp.Deframe` 按 magic 重新同步。
- **实时 vs 离线**:二者共用 `Process()`。实时源(afpacket,cgo)由消费方构造 `gopacket.PacketSource`
  后交给 `Process`,本包与 `cmd/pcapdump` 保持纯 Go。

## 6. 抓包与回放工具

- `scripts/capture.sh`:网关上 tcpdump 录 `tcp port 8195` 的 pcap(轮转、可开 ip_forward),
  root 运行,产物落 `./pcap/`(gitignore)。
- `cmd/pcapdump`:回放 pcap 输出「适合 AI 分析」的结构化文本。无参 = opcode 概览;
  `-op 0x1888,FREE` 转储匹配 opcode 的消息(hex/十进制/名称子串,`-hex` 附原始字节);
  `-gid 20508,15895` 扫描某宠物编号出现在哪些 opcode。转储默认按 `pbdesc`(`build/pbdesc`,
  `-data` 覆盖)精确解码出带字段名/枚举名的树,未映射或版本对不上时退回通用 wire 级解码;
  `-msg .Next.XxxRsp` 强制消息类型,`-wire` 强制只用 wire 级。
